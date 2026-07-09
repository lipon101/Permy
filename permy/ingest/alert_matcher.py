from __future__ import annotations

"""Alert matching — decide which saved alerts a newly-ingested permit triggers.

This is the brain between ingestion and webhook delivery. After a city adapter
ingests new permits, the worker runs each permit through ``match_alerts`` to
find active alerts whose ``query`` the permit satisfies. Each match becomes a
signed webhook delivery (handled by ``permy.ingest.webhooks`` + the arq worker).

The query shape mirrors ``/v1/permits/search`` params: city, state, zip, trade,
permit_type, status, contractor, keyword, min_valuation, max_valuation,
issued_after, issued_before. An empty/missing field matches everything (open
search), so a brand-new alert with ``{}`` fires on every permit — which is the
right default for a "tell me everything in Austin" alert.

Pure + dependency-free so it's trivially unit-testable; the worker wires it to
the repo + the delivery queue.
"""
from dataclasses import dataclass, field  # noqa: E402
from datetime import date  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

from permy.models.schemas import Alert, Permit  # noqa: E402
from permy.scoring.lead_score import score_permit  # noqa: E402


@dataclass
class AlertMatch:
    """One alert that a permit triggered."""
    alert: Alert
    permit: Permit
    lead_score: int
    recommended_action: str
    reason: str
    # which query clauses matched (for the webhook payload + debugging)
    matched_clauses: List[str] = field(default_factory=list)


def _matches_clause(permit: Permit, key: str, value: Any) -> Optional[bool]:
    """Return True/False for a clause, or None if the clause is absent (open)."""
    if value is None or value == "":
        return None
    if key == "city":
        return (permit.address.city or "").lower() == str(value).lower()
    if key == "state":
        return (permit.address.state or "").lower() == str(value).lower()
    if key == "zip":
        return (permit.address.zip or "") == str(value)
    if key == "trade":
        return permit.trade_category == str(value)
    if key == "permit_type":
        return (permit.permit_type_normalized or "").lower() == str(value).lower()
    if key == "status":
        return permit.current_status == str(value)
    if key == "contractor":
        return permit.contractor is not None and str(value).lower() in (permit.contractor.name or "").lower()
    if key == "keyword":
        return str(value).lower() in (permit.description or "").lower()
    if key == "min_valuation":
        return permit.valuation_usd is not None and permit.valuation_usd >= float(value)
    if key == "max_valuation":
        return permit.valuation_usd is not None and permit.valuation_usd <= float(value)
    if key == "issued_after":
        d = _coerce_date(value)
        return d is not None and permit.dates.issued is not None and permit.dates.issued >= d
    if key == "issued_before":
        d = _coerce_date(value)
        return d is not None and permit.dates.issued is not None and permit.dates.issued <= d
    # unknown clause → don't filter on it (forward-compatible)
    return None


def _coerce_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def permit_matches_query(permit: Permit, query: Dict[str, Any]) -> bool:
    """True when a permit satisfies EVERY present clause in the query.

    Absent/empty clauses are open (match anything). This mirrors the
    /v1/permits/search AND-semantics so an alert's query behaves exactly like a
    manual search.
    """
    for key, value in (query or {}).items():
        result = _matches_clause(permit, key, value)
        if result is False:
            return False
    return True


def match_alerts(
    permit: Permit,
    alerts: List[Alert],
    market_hotspot_by_zip: Optional[Dict[str, int]] = None,
) -> List[AlertMatch]:
    """Return every active alert whose query the permit satisfies.

    For each match we score the permit under the alert's persona so the webhook
    payload carries a lead_score + recommended_action + reason — receivers get a
    ready-to-act signal, not just a raw permit.
    """
    matches: List[AlertMatch] = []
    hot = (market_hotspot_by_zip or {}).get(permit.address.zip or "")
    for alert in alerts:
        if not alert.is_active:
            continue
        if not permit_matches_query(permit, alert.query):
            continue
        matched_clauses = [k for k, v in (alert.query or {}).items()
                           if v not in (None, "") and _matches_clause(permit, k, v) is not False]
        b = score_permit(permit, persona=alert.persona, market_hotspot=hot)
        matches.append(AlertMatch(
            alert=alert, permit=permit,
            lead_score=b.lead_score, recommended_action=b.recommended_action,
            reason=b.reason, matched_clauses=matched_clauses,
        ))
    return matches


def build_webhook_payload(match: AlertMatch) -> Dict[str, Any]:
    """The ``data`` object delivered in the webhook event for one match."""
    return {
        "alert_id": match.alert.id,
        "persona": match.alert.persona,
        "matched_clauses": match.matched_clauses,
        "lead_score": match.lead_score,
        "recommended_action": match.recommended_action,
        "reason": match.reason,
        "permit": match.permit.model_dump(mode="json"),
    }


__all__ = ["AlertMatch", "match_alerts", "permit_matches_query", "build_webhook_payload"]
