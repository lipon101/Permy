from __future__ import annotations

"""The ingestion pipeline — ties adapters + enrichment steps into one flow.

    fetch → normalize → geocode → classify → license join → score → dedupe → store

This is the offline/batch path. The same `process_record` function is used by
the queue worker for incremental near-real-time pulls (a few high-value cities).
Pure-ish: I/O (geocode, DB) is injected so the pipeline is unit-testable.
"""
from datetime import date  # noqa: E402
from typing import Any, Callable, Dict, Optional  # noqa: E402

from permy.adapters.base import ADAPTERS, CityAdapter  # noqa: E402
from permy.core.confidence import overall_confidence  # noqa: E402
from permy.ingest.classify import classify_trade  # noqa: E402
from permy.ingest.license import get_board  # noqa: E402
from permy.models.schemas import Enrichment, Permit  # noqa: E402
from permy.scoring.lead_score import score_permit  # noqa: E402

Geocoder = Callable[[str], Optional[Any]]  # returns (lat,lng,conf) or None
Persister = Callable[[Permit], None]


def process_record(
    raw: Dict[str, Any],
    adapter: CityAdapter,
    geocoder: Optional[Geocoder] = None,
    market_hotspot_by_zip: Optional[Dict[str, int]] = None,
) -> Permit:
    """Process ONE raw upstream record → fully enriched Permit (no persistence)."""
    p = adapter.normalize(raw)

    # canonical id: respect the adapter's readable "{slug}:{source_id}" form.
    # Adapters set this in normalize(); we only backfill a hash-based fallback if
    # an adapter forgot to (defensive). Keeping ONE scheme everywhere is what
    # makes UPSERT dedupe work across re-ingests — see seed_from_fixture + cli.
    if not p.canonical_uid:
        from permy.ingest.dedupe import canonical_permit_uid
        p.canonical_uid = canonical_permit_uid(p.jurisdiction_slug, p.source_permit_id)

    # geocode (if not already present from the feed)
    if p.address.lat is None and geocoder is not None and p.address.full:
        res = geocoder(p.address.full)
        if res:
            lat, lng, conf = res
            p.address.lat = lat
            p.address.lng = lng
            p.address.geocode_confidence = conf

    # classify unknown trades
    if p.trade_category == "unknown":
        p.trade_category = classify_trade(p.description, p.permit_type_normalized)  # type: ignore

    # license join (best-effort, never blocks)
    if p.contractor and p.contractor.license and p.address.state:
        board = get_board(p.address.state)
        if board:
            info = board.lookup(p.contractor.license)
            if info:
                p.contractor.license_status = info.get("status")

    # confidence + score
    fields = {
        "valuation_usd": p.valuation_usd, "issued_date": p.dates.issued,
        "trade_category": p.trade_category,
        "contractor_id": p.contractor.name if p.contractor else None,
        "geom": p.address.lat, "description": p.description,
    }
    conf = overall_confidence(adapter.source_portal, True, p.last_checked_at, fields)
    hot = (market_hotspot_by_zip or {}).get(p.address.zip or "")
    b = score_permit(p, persona="general", market_hotspot=hot)
    p.enrichment = Enrichment(
        lead_score=b.lead_score, recommended_action=b.recommended_action,  # type: ignore
        reason=b.reason, dq_flags=b.dq_flags, confidence=conf,
    )
    return p


def run_ingest(
    jurisdiction_slug: str,
    since: Optional[date] = None,
    limit: int = 1000,
    geocoder: Optional[Geocoder] = None,
    persister: Optional[Persister] = None,
    market_hotspot_by_zip: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """Run a full ingestion pass for one city. Returns counts."""
    adapter = ADAPTERS[jurisdiction_slug]
    raws = adapter.fetch(since=since, limit=limit)
    processed = 0
    for raw in raws:
        p = process_record(raw, adapter, geocoder=geocoder, market_hotspot_by_zip=market_hotspot_by_zip)
        if persister:
            persister(p)
        processed += 1
    return {"fetched": len(raws), "processed": processed}
