from __future__ import annotations

"""Orlando, FL adapter — City of Orlando Socrata Open Data (Tyler Data & Insights).

Dataset: data.cityoforlando.net resource ryhf-m453 "Permit Applications".
No auth required. Refreshed nightly. Application-stage data = the EARLIEST
intent signal (a permit applied-for today, before it's issued) — high value for
lead-gen buyers who want to be first to call.

Endpoint: https://data.cityoforlando.net/resource/ryhf-m453.json

Field notes (captured live 2026-07-10):
  permit_number            "BLD2025-19013" / "MEC2026-12097" / "ELE2026-13432"
  application_type         "Building Permit" / "Mechanical Permit" / "Electrical"
                           / "Plumbing" / "Fire Permit" / "GAS" / "Demolition Permit"
  application_status       "Open" / "Issued" / "Finaled" / "Closed" / "Completed"
                           / "Stop Work" / "In Review" / "Hold" / "Void"
  worktype                 "New" / "Alteration" / "Repair" / "Addition" / "Demolition"
  issue_permit_date        ISO8601 (issued)
  processed_date           ISO8601 (applied/processed)
  permit_address           "1730 WELTIN ST"  (street only — no separate zip field)
  neighborhood             "Colonialtown North"  (95% fill; Orlando has no ZIP in feed)
  contractor_name          company name  (preferred, ~89% fill)
  contractor               individual name + company  (fallback)
  contractor_address       "1637 SUNBURST WAY,KISSIMMEE, FL 34744"
  parcel_owner_name        parcel owner
  property_owner_name      property owner
  estimated_cost           declared job value (USD)
  square_footage           project sqft
  parcel_number            parcel id
  geocoded_column          GeoJSON Point {type:Point, coordinates:[lng, lat]}
  project_name             project narrative

Honest gaps:
  * No contractor phone.
  * No ZIP code in the feed (Orlando uses neighborhood, not ZIP) — we leave zip null.
  * Owner published (parcel_owner_name / property_owner_name) — better than most.
"""
from datetime import date  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

import httpx  # noqa: E402

from permy.adapters.base import (  # noqa: E402
    Address,
    ContractorRef,
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

RESOURCE_ID = "ryhf-m453"
BASE_URL = f"https://data.cityoforlando.net/resource/{RESOURCE_ID}.json"

# application_type → trade
ORLANDO_TYPE_MAP = {
    "building permit": "building",
    "mechanical permit": "hvac",
    "electrical": "electrical",
    "plumbing": "plumbing",
    "fire permit": "other",
    "gas": "other",
    "demolition permit": "demolition",
}


def _trade(app_type: Optional[str], worktype: Optional[str], contractor_name: Optional[str]) -> str:
    s = " ".join(filter(None, [app_type, worktype, contractor_name])).lower()
    base = ORLANDO_TYPE_MAP.get((app_type or "").lower())
    if base and base != "building":
        return base
    if "roof" in s:
        return "roofing"
    if "solar" in s:
        return "solar"
    if "electr" in s:
        return "electrical"
    if "plumb" in s:
        return "plumbing"
    if "mechan" in s or "hvac" in s or "cooling" in s or "air condition" in s:
        return "hvac"
    if "demol" in s:
        return "demolition"
    if "new" in s and ("building" in s or "construction" in s):
        return "building"
    return base or "general"


def _work_class(worktype: Optional[str], app_type: Optional[str]) -> str:
    s = " ".join(filter(None, [worktype, app_type])).lower()
    if "demol" in s:
        return "demolition"
    if "new" in s:
        return "new_construction"
    if "addition" in s:
        return "addition"
    if "alter" in s or "remodel" in s or "repair" in s or "renov" in s:
        return "alteration"
    return "other"


def _status(app_status: Optional[str]) -> str:
    s = (app_status or "").strip().lower()
    return {
        "issued": "issued",
        "finaled": "final",
        "closed": "final",
        "completed": "final",
        "open": "active",
        "stop work": "active",
        "in review": "applied",
        "hold": "applied",
        "hardhold": "applied",
        "void": "cancelled",
    }.get(s, "unknown")


class OrlandoAdapter:
    jurisdiction_slug = "orlando-fl"
    city = "Orlando"
    state = "FL"
    source_portal = "socrata"
    source_name = "City of Orlando — Permit Applications (data.cityoforlando.net)"

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        if settings.socrata_app_token:
            self._client.headers["X-App-Token"] = settings.socrata_app_token

    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"$limit": limit, "$order": "issue_permit_date DESC",
                                  "$where": "issue_permit_date IS NOT NULL"}
        if since is not None:
            iso = since.strftime("%Y-%m-%d")
            params["$where"] = f"issue_permit_date >= '{iso}'"
        url = f"{BASE_URL}?{urlencode(params)}"
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        permit_num = _str(raw.get("permit_number"))
        app_type = _str(raw.get("application_type"))
        worktype = _str(raw.get("worktype"))

        # address: Orlando publishes street only (no ZIP in feed); city/state fixed
        street = _str(raw.get("permit_address"))
        full = ", ".join([x for x in [street, "Orlando", "FL"] if x])

        # GeoJSON point: geocoded_column {type:Point, coordinates:[lng, lat]}
        lat = None
        lng = None
        geocode_conf = None
        geo = raw.get("geocoded_column")
        if isinstance(geo, dict):
            coords = geo.get("coordinates")
            if isinstance(coords, list) and len(coords) == 2:
                lng = _float(coords[0])
                lat = _float(coords[1])
                if lat is not None and lng is not None:
                    geocode_conf = 0.9

        valuation = _float(raw.get("estimated_cost"))

        # contractor: prefer company name, fall back to individual
        contractor = None
        cname = _str(raw.get("contractor_name"))
        cind = _str(raw.get("contractor"))
        name = cname or cind
        if name:
            contractor = ContractorRef(name=name, license=None, license_state="FL",
                                       trade=app_type, phone=None)

        # owner: Orlando publishes both parcel + property owner — rare and valuable
        owner = None
        oname = _str(raw.get("parcel_owner_name")) or _str(raw.get("property_owner_name"))
        owner = OwnerRef(name=oname)

        wc = _work_class(worktype, app_type)
        ts = now_utc()
        synthetic_id = f"orlando-fl:{permit_num}"

        # source_url — Orlando public permit lookup
        source_url = None
        if permit_num:
            source_url = f"https://orp.cloudpermits.com/orlando/permit/{permit_num}"

        return Permit(
            id=synthetic_id,
            canonical_uid=f"orlando-fl:{permit_num}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=permit_num or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street, city="Orlando", state="FL", zip=None,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=app_type,
            permit_type_normalized=app_type,
            work_class=wc,  # type: ignore[arg-type]
            trade_category=_trade(app_type, worktype, cname),  # type: ignore[arg-type]
            is_new_construction=(wc == "new_construction"),
            is_alteration=(wc == "alteration"),
            is_demolition=(wc == "demolition"),
            valuation_usd=valuation,
            housing_units=None,
            new_add_sqft=_int(raw.get("square_footage")),
            dates=PermitDates(
                applied=_date(raw.get("processed_date")),
                issued=_date(raw.get("issue_permit_date")),
                finaled=None,
                expired=None,
            ),
            current_status=_status(raw.get("application_status")),  # type: ignore[arg-type]
            status_raw=_str(raw.get("application_status")),
            description=_str(raw.get("project_name")) or _str(raw.get("worktype")),
            contractor=contractor,
            owner=owner,
            parcel_id=_str(raw.get("parcel_number")),
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "city": self.city,
            "state": self.state,
            "source_portal": self.source_portal,
            "source_name": self.source_name,
            "source_home_url": "https://data.cityoforlando.net/Permitting/Permit-Applications/ryhf-m453",
            "is_live": True,
            "ingest_cadence": "daily",
            "coverage": {
                "permits": True,
                "valuation": True,      # estimated_cost
                "contractor": True,     # contractor_name + contractor individual
                "owner": True,          # parcel_owner_name + property_owner_name
                "phone": False,         # not published
                "geocode": True,        # GeoJSON Point
            },
        }


orlando = OrlandoAdapter()
register(orlando)
