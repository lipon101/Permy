from __future__ import annotations

"""Common city-adapter interface.

Every city's open-data portal speaks a different dialect (Socrata SoQL,
ArcGIS FeatureService, Accela, Tyler, CKAN, custom). Adapters hide that behind
one interface so the ingestion pipeline stays city-agnostic:

    fetch()   → raw upstream records (list[dict])
    normalize(raw) → Permit (canonical cross-city schema)
    source_meta()  → jurisdiction metadata for the coverage page

A given adapter ONLY does fetch + normalize. geocoding, classification,
license joins, scoring, and dedupe happen downstream in the pipeline
(see permy.ingest) so adapters stay thin and testable in isolation.

Register adapters in ADAPTERS below; the worker iterates them on cron.
"""
from datetime import date, datetime, timezone  # noqa: E402
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable  # noqa: E402

from permy.models.schemas import (  # noqa: E402
    Address,
    ContractorRef,
    Enrichment,
    OwnerRef,
    Permit,
    PermitDates,
)


@runtime_checkable
class CityAdapter(Protocol):
    jurisdiction_slug: str
    city: str
    state: str
    source_portal: str
    source_name: str

    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        """Pull raw upstream records. `since` enables incremental pulls."""
        ...

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        """Map one raw upstream record → canonical Permit."""
        ...

    def source_meta(self) -> Dict[str, Any]:
        """Jurisdiction + coverage metadata for the coverage page."""
        ...


# ---- registry (populated by importing city modules) ----
ADAPTERS: Dict[str, CityAdapter] = {}


def register(adapter: CityAdapter) -> CityAdapter:
    if not adapter.jurisdiction_slug:
        raise ValueError("adapter missing jurisdiction_slug")
    ADAPTERS[adapter.jurisdiction_slug] = adapter
    return adapter


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _date(v: Any) -> Optional[date]:
    """Parse Socrata-style ISO8601 (with or without trailing .000 / TZ)."""
    if not v:
        return None
    s = str(v)
    # Socrata returns e.g. "2026-07-08T00:00:00.000"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        # try date-only
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "CityAdapter", "ADAPTERS", "register",
    "Address", "ContractorRef", "Enrichment", "OwnerRef", "Permit", "PermitDates",
    "_str", "_int", "_float", "_date", "now_utc",
]
