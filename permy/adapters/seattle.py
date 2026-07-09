from __future__ import annotations

"""Seattle, WA adapter — data.seattle.gov Socrata Open Data API (SODA).

Dataset: data.seattle.gov resource 76t5-zqzr "Building Permits" (SDCI).
No auth required for public reads.

Endpoint: https://data.seattle.gov/resource/76t5-zqzr.json

Field notes (captured live 2026-07-09, 20 fields):
  permitnum              stable permit number
  permitclass            "Single Family/Duplex", "Multifamily", "Commercial", "Institutional"
  permitclassmapped      "Residential" / "Commercial" / "Institutional"
  permittypemapped       "New", "Addition/Alteration", "Demolition", "Building", ...
  statuscurrent          "Active", "Permit Issued", "Additional Info Requested", "Final", ...
  estprojectcost         estimated/declared project cost (valuation)
  housingcategory        housing category tag
  housingunits           dwelling units
  applieddate / issueddate / expiresdate   ISO8601
  description            work description narrative
  originaladdress1       street address
  originalcity / originalstate / originalzip
  latitude / longitude   explicit decimal-degree fields (separate, not GeoJSON)
  link {url}             link to the SDCI record portal
  dependentbuilding      related building id

Honest gaps:
  * No contractor name in the main feed (Seattle publishes contractor on a
    separate application detail, not this permits list).
  * No owner name published.
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

RESOURCE_ID = "76t5-zqzr"
BASE_URL = f"https://data.seattle.gov/resource/{RESOURCE_ID}.json"


def _trade(permitclassmapped: Optional[str], permittypemapped: Optional[str],
           description: Optional[str]) -> str:
    s = " ".join(filter(None, [permitclassmapped, permittypemapped, description])).lower()
    if "demol" in s:
        return "demolition"
    if "solar" in s:
        return "solar"
    if "roof" in s:
        return "roofing"
    if "electr" in s:
        return "electrical"
    if "plumb" in s:
        return "plumbing"
    if "mechan" in s or "hvac" in s:
        return "hvac"
    if "new" in s and ("building" in s or "construction" in s):
        return "building"
    if "addition" in s or "alter" in s:
        return "general"
    return "general"


def _work_class(permittypemapped: Optional[str]) -> str:
    s = (permittypemapped or "").lower()
    if "demol" in s:
        return "demolition"
    if "new" in s:
        return "new_construction"
    if "addition" in s or "alter" in s:
        return "alteration"
    if "repair" in s or "remodel" in s:
        return "alteration"
    return "other"


def _status(status: Optional[str]) -> str:
    s = (status or "").strip().lower()
    if "issued" in s:
        return "issued"
    if "final" in s or "completed" in s:
        return "final"
    if "expire" in s:
        return "expired"
    if "withdraw" in s or "cancel" in s or "void" in s:
        return "cancelled"
    if "active" in s:
        return "active"
    if "request" in s or "pending" in s or "review" in s or "intake" in s:
        return "applied"
    return "unknown"


class SeattleAdapter:
    jurisdiction_slug = "seattle-wa"
    city = "Seattle"
    state = "WA"
    source_portal = "socrata"
    source_name = "Seattle SDCI — Building Permits (data.seattle.gov)"

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        if settings.socrata_app_token:
            self._client.headers["X-App-Token"] = settings.socrata_app_token

    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"$limit": limit, "$order": "applieddate DESC"}
        if since is not None:
            iso = since.strftime("%Y-%m-%d")
            params["$where"] = f"applieddate >= '{iso}'"
        url = f"{BASE_URL}?{urlencode(params)}"
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        permit_num = _str(raw.get("permitnum"))
        pclass_mapped = _str(raw.get("permitclassmapped"))
        ptype_mapped = _str(raw.get("permittypemapped"))

        street = _str(raw.get("originaladdress1"))
        city = _str(raw.get("originalcity")) or "Seattle"
        state = _str(raw.get("originalstate")) or "WA"
        zipc = _str(raw.get("originalzip"))
        full = ", ".join([x for x in [street, city, state, zipc] if x])

        # Seattle publishes explicit latitude / longitude fields (decimal degrees)
        lat = _float(raw.get("latitude"))
        lng = _float(raw.get("longitude"))
        geocode_conf = 0.9 if (lat is not None and lng is not None) else None

        # link → source_url
        source_url = None
        link = raw.get("link")
        if isinstance(link, dict):
            source_url = _str(link.get("url"))
        elif isinstance(link, str):
            source_url = link

        valuation = _float(raw.get("estprojectcost"))
        wc = _work_class(ptype_mapped)
        ts = now_utc()
        synthetic_id = f"seattle-wa:{permit_num}"

        return Permit(
            id=synthetic_id,
            canonical_uid=f"seattle-wa:{permit_num}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=permit_num or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street, city=city, state=state, zip=zipc,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=_str(raw.get("permitclass")),
            permit_type_normalized=ptype_mapped or pclass_mapped,
            work_class=wc,  # type: ignore[arg-type]
            trade_category=_trade(pclass_mapped, ptype_mapped, raw.get("description")),  # type: ignore[arg-type]
            is_new_construction=(wc == "new_construction"),
            is_alteration=(wc == "alteration"),
            is_demolition=(wc == "demolition"),
            valuation_usd=valuation,
            housing_units=_int(raw.get("housingunits")),
            new_add_sqft=None,
            dates=PermitDates(
                applied=_date(raw.get("applieddate")),
                issued=_date(raw.get("issueddate")),
                finaled=None,
                expired=_date(raw.get("expiresdate")),
            ),
            current_status=_status(raw.get("statuscurrent")),  # type: ignore[arg-type]
            status_raw=_str(raw.get("statuscurrent")),
            description=_str(raw.get("description")),
            contractor=None,  # not in main feed
            owner=OwnerRef(name=None),
            parcel_id=None,
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "city": self.city,
            "state": self.state,
            "source_portal": self.source_portal,
            "source_name": self.source_name,
            "source_home_url": "https://data.seattle.gov/Permitting/Building-Permits/76t5-zqzr",
            "is_live": True,
            "ingest_cadence": "daily",
            "coverage": {
                "permits": True,
                "valuation": True,      # estprojectcost
                "contractor": False,    # not in main feed
                "owner": False,
                "phone": False,
                "geocode": True,        # explicit lat/lng fields
            },
        }


seattle = SeattleAdapter()
register(seattle)
