from __future__ import annotations

"""Trade classification — rule/keyword maps per trade.

The Austin adapter does a first-cut classification from explicit trade fields.
This module is the SHARED, city-agnostic classifier run by the pipeline on
records whose trade is still 'unknown' (or to refine an existing guess).

MVP = deterministic keyword maps (no LLM). A cheap-LLM refinement pass for the
top uncertain records is a Phase 7+ enhancement — kept behind a flag so the
deterministic path stays the default and remains auditable.
"""
from typing import Optional  # noqa: E402

from permy.core.config import TRADE_KEYWORDS  # noqa: E402


def classify_trade(description: Optional[str], permit_type_desc: Optional[str] = None) -> str:
    """First-match keyword classification → canonical trade_category.

    Order matters: specific trades (roofing, solar, hvac) checked before
    generic 'building'/'general'. Returns 'unknown' if nothing matches.
    """
    text = " ".join(filter(None, [description, permit_type_desc])).lower()
    if not text:
        return "unknown"
    # ordered check
    for trade in ("roofing", "solar", "hvac", "plumbing", "electrical", "demolition", "building", "general"):
        for kw in TRADE_KEYWORDS.get(trade, []):
            if kw in text:
                return trade
    return "unknown"


def classify_work_class(work_raw: Optional[str]) -> str:
    """Map a raw work-class string → canonical work_class enum."""
    if not work_raw:
        return "unknown"
    s = work_raw.strip().lower()
    m = {
        "new": "new_construction", "new construction": "new_construction",
        "addition": "addition", "remodel": "remodel", "renovation": "remodel",
        "repair": "repair", "demolition": "demolition", "demolish": "demolition",
        "alteration": "alteration", "tenant finish": "alteration",
    }
    return m.get(s, "other")
