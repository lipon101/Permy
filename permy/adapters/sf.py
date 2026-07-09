from __future__ import annotations

"""San Francisco, CA adapter — DataSF Socrata Open Data API (SODA).

Dataset: data.sfgov.org resource i98e-djp9 "Building Permits" (DBI).
~1.28M permits since 2013. No auth required for public reads.

Endpoint: https://data.sfgov.org/resource/i98e-djp9.json

Field notes (captured live 2026-07-09, 39 fields):
  permit_number          stable permit id
  permit_type            code ("3" = additions/alterations/repairs, "1" = new construction, ...)
  permit_type_definition human label ("additions alterations or repairs", "new construction", ...)
  status                 "approved", "issued", "filed", "withdrawn", "cancelled", "expired", ...
  filed_date             ISO8601 (application filed)
  issued_date            ISO8601 (issued) — often null on in-review records
  status_date            ISO8601 (last status change)
  estimated_cost         original declared cost
  revised_cost           revised declared cost (use when present, else estimated)
  existing_use / proposed_use   occupancy descriptions
  proposed_units         dwelling units proposed
  number_of_proposed_stories
  street_number / street_name / street_suffix / zipcode
  block / lot            parcel identifiers
  neighborhoods_analysis_boundaries   neighborhood
  location               GeoJSON Point {type:Point, coordinates:[lng, lat]}  (!)
  permit_creation_date   record creation
  data_as_of             upstream freshness watermark

Honest gaps:
  * No contractor on the DBI main permit record.
  * No owner name published.
  * Valuation present (revised_cost > estimated_cost).
"""
from datetime import date  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

import httpx  # noqa: E402

from permy.adapters.base import (  # noqa: E402
    Address,
    Enrichment,
    OwnerRef,
    Permit,
    PermitDates,
    _date,
    _float,
    _int,
    _str,
    now_utc,
    register,
)
from permy.core.config import settings  # noqa: E402

RESOURCE_ID = "i98e-djp9"
BASE_URL = f"https://data.sfgov.org/resource/{RESOURCE_ID}.json"

# SF permit_type code → normalized label
SF_PERMITTYPE_MAP = {
    "1": "New Construction",
    "2": "Additions, Alterations or Repairs",
    "3": "Additions, Alterations or Repairs",
    "4": "Sign Permit",
    "5": "Demolition Permit",
    "6": "Other (Non-Permit)",
    "7": "Other (Non-Permit)",
    "8": "Condominium Conversion",
}


def _trade(permit_type_def: Optional[str], existing_use: Optional[str],
           proposed_use: Optional[str]) -> str:
    s = " ".join(filter(None, [permit_type_def, existing_use, proposed_use])).lower()
    if "demol" in s:
        return "demolition"
    if "new construction" in s:
        return "building"
    if "roof" in s:
        return "roofing"
    if "solar" in s:
        return "solar"
    if "electr" in s:
        return "electrical"
    if "plumb" in s:
        return "plumbing"
    if "mechan" in s or "hvac" in s:
        return "hvac"
    return "general"


def _work_class(permit_type_def: Optional[str]) -> str:
    s = (permit_type_def or "").lower()
    if "new construction" in s:
        return "new_construction"
    if "demol" in s:
        return "demolition"
    if "addition" in s or "alter" in s or "repair" in s or "remodel" in s:
        return "alteration"
    return "other"


def _status(status: Optional[str]) -> str:
    s = (status or "").strip().lower()
    return {
        "issued": "issued",
        "approved": "issued",       # SF "approved" ≈ issued-ready
        "filed": "applied",
        "withdrawn": "withdrawn",
        "cancelled": "cancelled",
        "expired": "expired",
        "suspend": "active",
        "reinstated": "active",
        "open": "applied",
    }.get(s, "unknown")


class SFAdapter:
    jurisdiction_slug = "sf-ca"
    city = "San Francisco"
    state = "CA"
    source_portal = "socrata"
    source_name = "SF Dept of Building Inspection — Building Permits (data.sfgov.org)"

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        if settings.socrata_app_token:
            self._client.headers["X-App-Token"] = settings.socrata_app_token

    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"$limit": limit, "$order": "filed_date DESC"}
        if since is not None:
            iso = since.strftime("%Y-%m-%d")
            params["$where"] = f"filed_date >= '{iso}'"
        url = f"{BASE_URL}?{urlencode(params)}"
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        permit_num = _str(raw.get("permit_number"))
        ptype = _str(raw.get("permit_type"))
        ptype_def = _str(raw.get("permit_type_definition"))

        # address
        street_num = _str(raw.get("street_number")) or ""
        street_name = _str(raw.get("street_name")) or ""
        street_suffix = _str(raw.get("street_suffix")) or ""
        street = " ".join(p for p in [street_num, street_name, street_suffix] if p).strip() or None
        zipc = _str(raw.get("zipcode"))
        full = ", ".join([x for x in [street, "San Francisco", "CA", zipc] if x])

        # GeoJSON location: {type:Point, coordinates:[lng, lat]}
        lat = None
        lng = None
        geocode_conf = None
        loc = raw.get("location")
        if isinstance(loc, dict):
            coords = loc.get("coordinates")
            if isinstance(coords, list) and len(coords) == 2:
                lng = _float(coords[0])
                lat = _float(coords[1])
                if lat is not None and lng is not None:
                    geocode_conf = 0.95  # rooftop-ish from DBI

        # valuation: revised_cost (preferred) → estimated_cost
        valuation = _float(raw.get("revised_cost")) or _float(raw.get("estimated_cost"))

        ts = now_utc()
        synthetic_id = f"sf-ca:{permit_num}"

        # source_url — SF provides a permit detail link via the DBI records portal
        source_url = None
        if permit_num:
            source_url = f"https://dbiweb.sfgov.org/Default.aspx?page=PermitSearch&permit_number={permit_num}"

        wc = _work_class(ptype_def)

        return Permit(
            id=synthetic_id,
            canonical_uid=f"sf-ca:{permit_num}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=permit_num or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street, city="San Francisco", state="CA", zip=zipc,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=ptype,
            permit_type_normalized=ptype_def or SF_PERMITTYPE_MAP.get(ptype or ""),
            work_class=wc,  # type: ignore[arg-type]
            trade_category=_trade(ptype_def, raw.get("existing_use"), raw.get("proposed_use")),  # type: ignore[arg-type]
            is_new_construction=(wc == "new_construction"),
            is_alteration=(wc == "alteration"),
            is_demolition=(wc == "demolition"),
            valuation_usd=valuation,
            housing_units=_int(raw.get("proposed_units")),
            new_add_sqft=None,
            dates=PermitDates(
                applied=_date(raw.get("filed_date")),
                issued=_date(raw.get("issued_date")),
                finaled=None,
                expired=None,
            ),
            current_status=_status(raw.get("status")),  # type: ignore[arg-type]
            status_raw=_str(raw.get("status")),
            description=" / ".join(filter(None, [raw.get("existing_use"), raw.get("proposed_use")])) or None,
            contractor=None,  # not on DBI main record
            owner=OwnerRef(name=None),
            parcel_id=" ".join(filter(None, [_str(raw.get("block")), _str(raw.get("lot"))])).strip() or None,
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "city": self.city,
            "state": self.state,
            "source_portal": self.source_portal,
            "source_name": self.source_name,
            "source_home_url": "https://data.sfgov.org/Housing-and-Buildings/Building-Permits/i98e-djp9",
            "is_live": True,
            "ingest_cadence": "daily",
            "coverage": {
                "permits": True,
                "valuation": True,      # revised_cost / estimated_cost
                "contractor": False,    # not on DBI main record
                "owner": False,
                "phone": False,
                "geocode": True,        # GeoJSON Point lat/lng
            },
        }


sf = SFAdapter()
register(sf)
