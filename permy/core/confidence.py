from __future__ import annotations

"""Confidence utilities.

`confidence` is a 0..1 float attached to every record and every derived signal.
It blends:
  - source confidence (official feed vs archive vs scraped)            [0..1]
  - freshness confidence (how recently we last verified the record)    [0..1]
  - field completeness (fraction of high-value fields present)         [0..1]

Weights: source 0.4, freshness 0.3, completeness 0.3
"""
from datetime import datetime, timezone, timedelta
from typing import Dict


def source_confidence(source_portal: str, is_live: bool) -> float:
    """Official open-data feeds are highest trust; archive/scraped lower."""
    base = {
        "socrata": 0.95,
        "arcgis":  0.93,
        "accela":  0.90,
        "tyler":   0.88,
        "ckan":    0.92,
        "custom":  0.80,
        "scrape":  0.60,
        "archive": 0.50,
    }.get(source_portal, 0.75)
    if not is_live:
        base = min(base, 0.55)  # archive/legacy source capped
    return round(base, 3)


def freshness_confidence(last_checked_at: datetime, now: datetime = None) -> float:
    """Decays from 1.0 (checked today) toward 0.2 over 30 days."""
    now = now or datetime.now(timezone.utc)
    if last_checked_at is None:
        return 0.2
    if last_checked_at.tzinfo is None:
        last_checked_at = last_checked_at.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last_checked_at).total_seconds() / 86400.0)
    # exponential-ish decay; floor 0.2
    return round(max(0.2, 1.0 - (days / 30.0)), 3)


def completeness_confidence(fields: Dict[str, object], high_value_keys=()) -> float:
    """Fraction of high-value fields that are non-null/non-empty."""
    keys = high_value_keys or (
        "valuation_usd", "issued_date", "trade_category", "contractor_id",
        "geom", "description",
    )
    present = 0
    for k in keys:
        v = fields.get(k)
        if v is not None and v != "" and v != [] and v != {}:
            present += 1
    return round(present / max(1, len(keys)), 3)


def overall_confidence(
    source_portal: str,
    is_live: bool,
    last_checked_at: datetime,
    fields: Dict[str, object],
    weights: Dict[str, float] = None,
) -> float:
    w = weights or {"source": 0.4, "freshness": 0.3, "completeness": 0.3}
    c = (
        w["source"] * source_confidence(source_portal, is_live)
        + w["freshness"] * freshness_confidence(last_checked_at)
        + w["completeness"] * completeness_confidence(fields)
    )
    return round(max(0.0, min(1.0, c)), 3)
