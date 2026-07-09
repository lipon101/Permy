from __future__ import annotations

from datetime import date, timedelta

import pytest

from permy.models.schemas import Address, ContractorRef, Enrichment, OwnerRef, Permit, PermitDates
from permy.scoring.lead_score import (
    PERSONA_WEIGHTS, PERSONA_TARGET_TRADES, _band, _dq_flags,
    rank_permits, score_permit, score_recency, score_valuation,
)


def _permit(
    *,
    trade="roofing",
    issued=None,
    valuation=50_000,
    phone="5125551234",
    work_class="alteration",
    housing_units=1,
    zipc="78704",
    new_add_sqft=None,
    contractor_name="Acme Roofing",
) -> Permit:
    today = date.today()
    if contractor_name:
        contractor = ContractorRef(name=contractor_name, phone=phone) if phone else ContractorRef(name=contractor_name)
    else:
        contractor = None
    return Permit(
        id="t1", canonical_uid="t1", jurisdiction_slug="austin-tx",
        source_permit_id="1", source_url="https://x", source_name="s",
        first_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        last_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        last_checked_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        address=Address(full="1 Test St, Austin, TX 78704", city="Austin", state="TX", zip=zipc, street="1 Test St"),
        trade_category=trade, work_class=work_class, is_alteration=(work_class == "alteration"),
        is_new_construction=(work_class == "new_construction"),
        valuation_usd=valuation, housing_units=housing_units, new_add_sqft=new_add_sqft,
        dates=PermitDates(issued=issued or (today - timedelta(days=10))),
        current_status="issued",
        contractor=contractor,
        owner=OwnerRef(name=None),
        enrichment=Enrichment(confidence=0.9),
    )


# ---- determinism ----
def test_scoring_is_deterministic():
    p = _permit()
    a = score_permit(p, persona="roofer")
    b = score_permit(p, persona="roofer")
    assert a.lead_score == b.lead_score
    assert a.reason == b.reason


def test_persona_weights_sum_to_100():
    for persona, w in PERSONA_WEIGHTS.items():
        assert sum(w.values()) == 100, f"{persona} weights sum {sum(w.values())}"


def test_reject_weights_not_summing_100():
    p = _permit()
    with pytest.raises(ValueError):
        score_permit(p, persona="roofer", weights={"recency": 10, "valuation": 10, "trade_fit": 10,
                                                     "property_fit": 10, "contactability": 10, "market_momentum": 10})


# ---- band boundaries ----
@pytest.mark.parametrize("score,expected", [
    (80, "call_now"), (79, "qualify"), (60, "qualify"), (59, "monitor"),
    (35, "monitor"), (34, "skip"), (0, "skip"), (100, "call_now"),
])
def test_band_boundaries(score, expected):
    assert _band(score) == expected


# ---- component scorers ----
def test_recency_decays():
    today = date.today()
    fresh = _permit(issued=today)
    old = _permit(issued=today - timedelta(days=200))
    assert score_recency(fresh) == 1.0
    assert score_recency(old) == 0.0


def test_recency_no_dates():
    p = _permit()
    p.dates = PermitDates()  # all None
    assert score_recency(p) == 0.0


def test_valuation_log_scaling():
    assert abs(score_valuation(_permit(valuation=None)) - 0.3) < 0.01
    assert score_valuation(_permit(valuation=1_000_000)) > score_valuation(_permit(valuation=10_000))


# ---- persona differentiation (the whole point) ----
def test_roofer_scores_roofing_higher_than_investor_does():
    p = _permit(trade="roofing", valuation=30_000, issued=date.today() - timedelta(days=5), work_class="alteration")
    roofer = score_permit(p, persona="roofer")
    investor = score_permit(p, persona="investor")
    # For a small residential roofing job, a roofer should score higher than an investor
    assert roofer.lead_score > investor.lead_score


def test_investor_scores_big_multifamily_higher_than_roofer():
    p = _permit(trade="building", valuation=2_000_000, housing_units=40,
                issued=date.today() - timedelta(days=30), work_class="new_construction")
    investor = score_permit(p, persona="investor")
    roofer = score_permit(p, persona="roofer")
    assert investor.lead_score > roofer.lead_score


def test_supplier_likes_new_construction():
    p = _permit(trade="building", valuation=800_000, work_class="new_construction",
                issued=date.today() - timedelta(days=20))
    supplier = score_permit(p, persona="supplier")
    assert supplier.lead_score >= 60  # should at least qualify


def test_contactability_rewards_phone():
    with_phone = score_permit(_permit(phone="5125551234"), persona="general")
    without = score_permit(_permit(phone=None), persona="general")
    assert with_phone.lead_score > without.lead_score


# ---- market momentum ----
def test_market_momentum_lifts_score():
    p = _permit()
    cold = score_permit(p, persona="general", market_hotspot=10)
    hot = score_permit(p, persona="general", market_hotspot=95)
    assert hot.lead_score > cold.lead_score


def test_market_momentum_none_is_neutral():
    p = _permit()
    b = score_permit(p, persona="general", market_hotspot=None)
    assert 0 <= b.lead_score <= 100


# ---- dq flags ----
def test_dq_flags_for_sparse_record():
    p = _permit(valuation=None, trade="unknown", phone=None, contractor_name="Acme")
    flags = _dq_flags(p)
    assert "valuation_unknown" in flags
    assert "trade_unclassified" in flags
    assert "no_phone" in flags
    assert "no_contractor" not in flags  # we DO have a contractor, just no phone


def test_reason_is_human_readable_and_mentions_persona():
    p = _permit(trade="roofing", valuation=45_000)
    b = score_permit(p, persona="roofer")
    assert b.reason.startswith("[roofer]")
    assert len(b.reason) > 10


def test_reason_includes_dq_warning():
    p = _permit(valuation=None, trade="unknown")
    b = score_permit(p, persona="general")
    assert "⚠" in b.reason


# ---- ranking ----
def test_rank_orders_by_score_desc():
    permits = [
        _permit(trade="roofing", valuation=200_000, issued=date.today() - timedelta(days=2)),
        _permit(trade="roofing", valuation=10_000, issued=date.today() - timedelta(days=80)),
        _permit(trade="roofing", valuation=80_000, issued=date.today() - timedelta(days=10)),
    ]
    ranked = rank_permits(permits, persona="roofer", limit=3)
    scores = [b.lead_score for _, b in ranked]
    assert scores == sorted(scores, reverse=True)
    # top permit should be the freshest + highest value one
    assert ranked[0][0].valuation_usd == 200_000


def test_rank_respects_limit():
    permits = [_permit() for _ in range(10)]
    ranked = rank_permits(permits, persona="roofer", limit=3)
    assert len(ranked) == 3


def test_custom_weights_override_persona():
    p = _permit()
    default = score_permit(p, persona="roofer")
    custom = score_permit(p, persona="roofer", weights={
        "recency": 50, "valuation": 0, "trade_fit": 50,
        "property_fit": 0, "contactability": 0, "market_momentum": 0,
    })
    # with only recency+trade_fit weighting, score should differ from default
    assert custom.lead_score != default.lead_score


def test_all_personas_produce_valid_scores():
    p = _permit(trade="roofing")
    for persona in PERSONA_WEIGHTS:
        b = score_permit(p, persona=persona)
        assert 0 <= b.lead_score <= 100
        assert b.recommended_action in ("call_now", "qualify", "monitor", "skip")


def test_target_trades_defined_for_all_personas():
    for persona in PERSONA_WEIGHTS:
        assert persona in PERSONA_TARGET_TRADES
        assert len(PERSONA_TARGET_TRADES[persona]) > 0
