from __future__ import annotations

"""Deterministic lead scoring — the core Permy differentiator.

lead_score is a weighted sum of six components, each scored 0..1 then scaled
to its weight, summing to a 0..100 integer:

    recency         0..25   (how fresh the permit signal is)
    valuation       0..25   (declared job value, log-scaled)
    trade_fit       0..20   (match between permit trade and the persona's target trades)
    property_fit    0..10   (property characteristics the persona cares about)
    contactability  0..10   (can we actually hand them a phone/license?)
    market_momentum 0..10   (ZIP-level development heat)

Weights are PERSONA-ADJUSTABLE: each persona rebalances which components matter.
The component *max weights* always sum to 100, but the distribution shifts.

Bands → recommended_action:
    >=80  call_now
    60-79 qualify
    35-59 monitor
    <35   skip

A human `reason` explains the top 2-3 contributing factors (and any dq_flags).

This module is PURE: no I/O, no network, no LLM. Same inputs → same score.
That determinism is a feature — it's auditable and testable.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from permy.models.schemas import Permit, Persona, RecommendedAction

# ---------------------------------------------------------------------------
# Persona weight presets. Each dict's values sum to 100.
# These are the *default* opinionated weights; the /v1/leads/ranked endpoint
# accepts optional overrides per call.
# ---------------------------------------------------------------------------
PERSONA_WEIGHTS: Dict[Persona, Dict[str, int]] = {
    "roofer": {
        "recency": 30, "valuation": 15, "trade_fit": 25, "property_fit": 10,
        "contactability": 10, "market_momentum": 10,
    },
    "solar": {
        "recency": 25, "valuation": 15, "trade_fit": 25, "property_fit": 15,
        "contactability": 10, "market_momentum": 10,
    },
    "hvac": {
        "recency": 28, "valuation": 17, "trade_fit": 22, "property_fit": 10,
        "contactability": 13, "market_momentum": 10,
    },
    "investor": {
        "recency": 10, "valuation": 30, "trade_fit": 10, "property_fit": 20,
        "contactability": 5, "market_momentum": 25,
    },
    "supplier": {
        "recency": 15, "valuation": 25, "trade_fit": 15, "property_fit": 5,
        "contactability": 10, "market_momentum": 30,
    },
    "insurer": {
        "recency": 12, "valuation": 15, "trade_fit": 20, "property_fit": 25,
        "contactability": 8, "market_momentum": 20,
    },
    "general": {
        "recency": 25, "valuation": 25, "trade_fit": 20, "property_fit": 10,
        "contactability": 10, "market_momentum": 10,
    },
}

# Which trades each persona targets (drives trade_fit)
PERSONA_TARGET_TRADES: Dict[Persona, set] = {
    "roofer": {"roofing"},
    "solar": {"solar", "electrical"},
    "hvac": {"hvac"},
    "investor": {"building", "general"},  # investors want renovation/new-build signals
    "supplier": {"building", "general", "roofing", "hvac"},  # materials demand
    "insurer": {"roofing", "electrical", "plumbing", "hvac"},  # risk-relevant trades
    "general": {"roofing", "solar", "hvac", "building", "general"},
}

# Value bands (USD) used for valuation scoring
VAL_BANDS = [
    (0, 5_000),
    (5_000, 25_000),
    (25_000, 100_000),
    (100_000, 500_000),
    (500_000, 5_000_000),
    (5_000_000, float("inf")),
]


@dataclass
class ScoreBreakdown:
    recency: float
    valuation: float
    trade_fit: float
    property_fit: float
    contactability: float
    market_momentum: float
    lead_score: int
    recommended_action: str
    reason: str
    dq_flags: List[str]

    def to_dict(self) -> Dict:
        return {
            "recency": round(self.recency, 3),
            "valuation": round(self.valuation, 3),
            "trade_fit": round(self.trade_fit, 3),
            "property_fit": round(self.property_fit, 3),
            "contactability": round(self.contactability, 3),
            "market_momentum": round(self.market_momentum, 3),
            "lead_score": self.lead_score,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
            "dq_flags": self.dq_flags,
        }


# ---------------------------------------------------------------------------
# Component scorers — each returns 0..1
# ---------------------------------------------------------------------------

def score_recency(permit: Permit, now: date = None) -> float:
    """Most recent activity (issued/applied) decays from 1.0 over 90 days, floor 0."""
    now = now or date.today()
    candidates = [d for d in (permit.dates.issued, permit.dates.applied, permit.dates.finaled) if d]
    if not candidates:
        return 0.0
    latest = max(candidates)
    days_ago = max(0, (now - latest).days)
    # full strength if <=7 days; linear decay to 0 at 180 days
    if days_ago <= 7:
        return 1.0
    return max(0.0, 1.0 - (days_ago - 7) / 173.0)


def score_valuation(permit: Permit) -> float:
    """Log-scaled: unknown=0.3, $5k=0.4, $25k=0.55, $100k=0.7, $500k=0.85, $5M+=1.0."""
    v = permit.valuation_usd
    if v is None or v <= 0:
        return 0.3
    # log10 banding
    import math
    lv = math.log10(max(1.0, v))
    # lv ranges ~0 (1$) to ~7 ($10M). Map [3, 7] → [0.4, 1.0]
    if lv < 3:
        return 0.4
    score = 0.4 + (lv - 3) * (0.6 / 4.0)  # +0.15 per decade
    return max(0.0, min(1.0, score))


def score_trade_fit(permit: Permit, persona: Persona) -> float:
    """1.0 if permit trade is a persona target; partial credit for adjacent trades."""
    target = PERSONA_TARGET_TRADES.get(persona, set())
    t = permit.trade_category
    if t in target:
        return 1.0
    # adjacent: building/general often accompany target trades via master permits
    if t in {"building", "general"} and "building" in target:
        return 0.5
    # unknown trade — small baseline so we don't zero-out unclassified records
    if t == "unknown":
        return 0.25
    return 0.1


def score_property_fit(permit: Permit, persona: Persona) -> float:
    """Heuristics on property characteristics the persona cares about."""
    score = 0.3  # baseline
    if persona in ("roofer", "solar") and permit.is_alteration and not permit.is_new_construction:
        score += 0.4  # alteration of existing roof → roofer/solar gold
    if persona == "investor" and permit.housing_units and permit.housing_units > 1:
        score += 0.3  # multi-family
    if persona == "supplier" and permit.is_new_construction:
        score += 0.4  # new build → materials demand
    if persona == "insurer" and permit.trade_category in {"roofing", "electrical", "plumbing"}:
        score += 0.3
    if permit.new_add_sqft and permit.new_add_sqft > 1000:
        score += 0.1
    return min(1.0, score)


def score_contactability(permit: Permit) -> float:
    """Can the buyer actually reach someone? Phone is king."""
    score = 0.0
    if permit.contractor:
        if permit.contractor.phone:
            score += 0.6
        if permit.contractor.license:
            score += 0.2
        if permit.contractor.name:
            score += 0.1
    if permit.owner and permit.owner.name:
        score += 0.1
    return min(1.0, score)


def score_market_momentum(market_hotspot: Optional[int]) -> float:
    """ZIP hotspot score 0..100 → 0..1."""
    if market_hotspot is None:
        return 0.4  # unknown market → neutral
    return min(1.0, max(0.0, market_hotspot / 100.0))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _band(score: int) -> RecommendedAction:
    if score >= 80:
        return "call_now"
    if score >= 60:
        return "qualify"
    if score >= 35:
        return "monitor"
    return "skip"


def _build_reason(
    components: Dict[str, Tuple[float, int]],
    permit: Permit,
    persona: Persona,
    dq_flags: List[str],
) -> str:
    """Top 2-3 contributing factors, human-readable."""
    # sort components by raw contribution (subscore * weight)
    ranked = sorted(components.items(), key=lambda kv: kv[1][0] * kv[1][1], reverse=True)
    parts: List[str] = []
    label = {
        "recency": "fresh signal",
        "valuation": "job value",
        "trade_fit": "trade match",
        "property_fit": "property fit",
        "contactability": "contactability",
        "market_momentum": "ZIP momentum",
    }
    for name, (sub, w) in ranked[:3]:
        if sub * w < 3:
            break
        parts.append(f"{label[name]}={int(sub*w)}/{w}")
    extras: List[str] = []
    if permit.trade_category and permit.trade_category != "unknown":
        extras.append(f"trade={permit.trade_category}")
    if permit.valuation_usd:
        extras.append(f"~${int(permit.valuation_usd):,}")
    if permit.dates.issued:
        extras.append(f"issued={permit.dates.issued.isoformat()}")
    reason = f"[{persona}] " + ", ".join(parts)
    if extras:
        reason += " (" + ", ".join(extras) + ")"
    if dq_flags:
        reason += " ⚠ " + "; ".join(dq_flags)
    return reason


def _dq_flags(permit: Permit) -> List[str]:
    flags: List[str] = []
    if permit.valuation_usd is None:
        flags.append("valuation_unknown")
    if permit.trade_category == "unknown":
        flags.append("trade_unclassified")
    if permit.contractor is None:
        flags.append("no_contractor")
    elif not permit.contractor.phone:
        flags.append("no_phone")
    if permit.address.geocode_confidence is not None and permit.address.geocode_confidence < 0.6:
        flags.append("weak_geocode")
    return flags


def score_permit(
    permit: Permit,
    persona: Persona = "general",
    market_hotspot: Optional[int] = None,
    weights: Optional[Dict[str, int]] = None,
    now: date = None,
) -> ScoreBreakdown:
    """Score a single permit for a persona. Pure + deterministic."""
    w = weights or PERSONA_WEIGHTS[persona]
    # validate weight sum (tolerate rounding to 100)
    total_w = sum(w.values())
    if abs(total_w - 100) > 1:
        raise ValueError(f"persona weights must sum to 100, got {total_w} for {persona}")

    rec = score_recency(permit, now)
    val = score_valuation(permit)
    tf = score_trade_fit(permit, persona)
    pf = score_property_fit(permit, persona)
    ct = score_contactability(permit)
    mm = score_market_momentum(market_hotspot)

    components = {
        "recency": (rec, w["recency"]),
        "valuation": (val, w["valuation"]),
        "trade_fit": (tf, w["trade_fit"]),
        "property_fit": (pf, w["property_fit"]),
        "contactability": (ct, w["contactability"]),
        "market_momentum": (mm, w["market_momentum"]),
    }

    lead_score = int(round(
        rec * w["recency"]
        + val * w["valuation"]
        + tf * w["trade_fit"]
        + pf * w["property_fit"]
        + ct * w["contactability"]
        + mm * w["market_momentum"]
    ))
    lead_score = max(0, min(100, lead_score))

    dq = _dq_flags(permit)
    action = _band(lead_score)
    reason = _build_reason(components, permit, persona, dq)

    return ScoreBreakdown(
        recency=rec, valuation=val, trade_fit=tf, property_fit=pf,
        contactability=ct, market_momentum=mm,
        lead_score=lead_score, recommended_action=action,
        reason=reason, dq_flags=dq,
    )


def rank_permits(
    permits: List[Permit],
    persona: Persona = "general",
    market_hotspot_by_zip: Optional[Dict[str, int]] = None,
    limit: int = 25,
) -> List[Tuple[Permit, ScoreBreakdown]]:
    """Score + sort a batch of permits for a persona. Returns top-N."""
    market_hotspot_by_zip = market_hotspot_by_zip or {}
    scored: List[Tuple[Permit, ScoreBreakdown]] = []
    for p in permits:
        hot = market_hotspot_by_zip.get(p.address.zip or "")
        b = score_permit(p, persona=persona, market_hotspot=hot)
        scored.append((p, b))
    scored.sort(key=lambda x: x[1].lead_score, reverse=True)
    return scored[:limit]
