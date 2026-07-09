from __future__ import annotations

"""New York City DOB adapter — Socrata Open Data API (SODA).

Dataset: data.cityofnewyork.us resource ipu4-2q9a "DOB Permit Issuance"
No auth required for public reads. NYC is unusually rich: publishes GIS
lat/lng, permittee (contractor) phone + license #, AND owner name (rare).

Endpoint base: https://data.cityofnewyork.us/resource/ipu4-2q9a.json

NYC DOB code maps:
  permit_type: EW=Electrical, PL=Plumbing, FO=Foundation, EQ=Equipment,
               AL=Alteration, NB=New Building, DM=Demolition, SG=Sign,
               MW=Mechanical, PL=Plumbing, ... (we map the common ones)
  job_type:    A1/A2/A3=Alteration (major/minor/other), NB=New Building,
               DM=Demolition, SG=Sign, FH=Filing (no work)
  work_type:   MH=Mechanical, PL=Plumbing, EW=Electrical, ... (sub-work codes)
"""
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from permy.adapters.base import (
    Address, ContractorRef, Enrichment, OwnerRef, Permit, PermitDates,
    _date, _float, _int, _str, now_utc, register,
)
from permy.core.config import settings

RESOURCE_ID = "ipu4-2q9a"
BASE_URL = f"https://data.cityofnewyork.us/resource/{RESOURCE_ID}.json"

# permit_type code → human label
NYC_PERMITTYPE_MAP = {
    "EW": "Electrical Permit",
    "PL": "Plumbing Permit",
    "EQ": "Equipment Work Permit",
    "FO": "Foundation Permit",
    "AL": "Alteration Permit",
    "NB": "New Building Permit",
    "DM": "Demolition Permit",
    "SG": "Sign Permit",
    "MW": "Mechanical Permit",
    "FH": "Filing Only (No Work)",
    "OP": "Occupancy Permit",
}

# job_type → work_class
NYC_JOBTYPE_MAP = {
    "A1": "alteration",   # major alteration
    "A2": "alteration",   # minor alteration (multiple work types)
    "A3": "alteration",   # other alteration (one work type)
    "NB": "new_construction",
    "DM": "demolition",
    "SG": "other",         # sign
    "FH": "other",         # filing, no work
}


def _trade_from_fields(permit_type: Optional[str], work_type: Optional[str],
                       permittee_license_type: Optional[str],
                       work_description: Optional[str]) -> str:
    """NYC trade inference from permit_type / work_type / license type."""
    s = " ".join(filter(None, [permit_type, work_type, permittee_license_type, work_description])).lower()
    if "electr" in s or s.startswith("ew"):
        return "electrical"
    if "plumb" in s or s.startswith("pl"):
        return "plumbing"
    if "mechan" in s or "mh" == (work_type or "").lower():
        return "hvac"
    if "demol" in s or "dm" == (permit_type or "").lower():
        return "demolition"
    if "sign" in s and "sg" == (permit_type or "").lower():
        return "other"
    if "new building" in s or "nb" == (permit_type or "").lower():
        return "building"
    if "alter" in s or "a1" == (permit_type or "").lower():
        return "building"
    if "gc" == (permittee_license_type or "").lower():  # General Contractor license
        return "general"
    return "unknown"


def _status(permit_status: Optional[str]) -> str:
    s = (permit_status or "").strip().lower()
    return {
        "issued": "issued",
        "active": "active",
        "filed": "applied",
        "in process": "applied",
        "approved": "issued",
        "withdrawn": "withdrawn",
        "revoked": "cancelled",
        "expired": "expired",
    }.get(s, "unknown")


class NYCAdapter:
    jurisdiction_slug = "nyc-ny"
    city = "New York"
    state = "NY"
    source_portal = "socrata"
    source_name = "NYC Department of Buildings — Permit Issuance (data.cityofnewyork.us)"

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        if settings.socrata_app_token:
            self._client.headers["X-App-Token"] = settings.socrata_app_token

    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"$limit": limit, "$order": "issuance_date DESC"}
        if since is not None:
            iso = since.strftime("%Y-%m-%d")
            params["$where"] = f"issuance_date >= '{iso}'"
        url = f"{BASE_URL}?{urlencode(params)}"
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        # source_permit_id: permit_si_no is the stable DOB permit sequence id
        source_id = _str(raw.get("permit_si_no")) or _str(raw.get("job__")) or _str(raw.get("permit_"))
        job_num = _str(raw.get("job__"))

        # address: house__ + street_name + borough + zip_code
        house = _str(raw.get("house__")) or ""
        street = _str(raw.get("street_name")) or ""
        borough = _str(raw.get("borough")) or "New York"
        zipc = _str(raw.get("zip_code"))
        street_full = " ".join(p for p in [house, street] if p).strip()
        full = ", ".join([x for x in [street_full, borough, "NY", zipc] if x])

        # NYC publishes GIS lat/lng directly (unlike Austin)
        lat = _float(raw.get("gis_latitude"))
        lng = _float(raw.get("gis_longitude"))
        geocode_conf = 0.9 if (lat is not None and lng is not None) else None

        # source_url — link to DOB BIS. We construct a stable BIS web link from the job #.
        source_url = None
        if job_num:
            source_url = (
                "https://a810-bisweb.nyc.gov/WebEB/eBIS/DocQuery/Description.aspx?"
                f"doctype=PW1&docid={job_num}"
            )

        permit_type_code = _str(raw.get("permit_type"))
        job_type = _str(raw.get("job_type"))
        work_type = _str(raw.get("work_type"))
        work_class = NYC_JOBTYPE_MAP.get(job_type or "", "other")

        # contractor (permittee)
        contractor = None
        biz = _str(raw.get("permittee_s_business_name"))
        first = _str(raw.get("permittee_s_first_name"))
        last = _str(raw.get("permittee_s_last_name"))
        cname = biz or " ".join(p for p in [first, last] if p).strip() or None
        if cname:
            contractor = ContractorRef(
                name=cname,
                license=_str(raw.get("permittee_s_license__")),
                license_state="NY",
                trade=_str(raw.get("permittee_s_license_type")),
                phone=_str(raw.get("permittee_s_phone__")),
            )

        # owner (NYC publishes owner — rare among cities)
        owner = None
        obiz = _str(raw.get("owner_s_business_name"))
        ofirst = _str(raw.get("owner_s_first_name"))
        olast = _str(raw.get("owner_s_last_name"))
        oname = obiz or " ".join(p for p in [ofirst, olast] if p).strip() or None
        owner = OwnerRef(name=oname)

        # valuation: NYC DOB Permit Issuance does NOT publish declared job value
        # (that's on the separate Job Application dataset). Honest null.
        valuation = None

        trade = _trade_from_fields(permit_type_code, work_type,
                                   _str(raw.get("permittee_s_license_type")),
                                   _str(raw.get("work_type")))

        ts = now_utc()
        synthetic_id = f"nyc-ny:{source_id}"

        return Permit(
            id=synthetic_id,
            canonical_uid=f"nyc-ny:{source_id}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=source_id or job_num or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street_full or None, city=borough, state="NY", zip=zipc,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=permit_type_code or job_num,
            permit_type_normalized=NYC_PERMITTYPE_MAP.get(permit_type_code or "", None),
            work_class=work_class,  # type: ignore[arg-type]
            trade_category=trade,  # type: ignore[arg-type]
            is_new_construction=(work_class == "new_construction"),
            is_alteration=(work_class == "alteration"),
            is_demolition=(work_class == "demolition"),
            valuation_usd=valuation,
            housing_units=None,  # not on issuance dataset
            new_add_sqft=None,
            dates=PermitDates(
                applied=_date(raw.get("filing_date")),
                issued=_date(raw.get("issuance_date")),
                expired=_date(raw.get("expiration_date")),
                finaled=None,
            ),
            current_status=_status(raw.get("permit_status")),  # type: ignore[arg-type]
            status_raw=_str(raw.get("permit_status")),
            description=None,  # DOB issuance has no narrative description
            contractor=contractor,
            owner=owner,
            parcel_id=_str(raw.get("bbl")) or _str(raw.get("bin__")),
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "city": self.city,
            "state": self.state,
            "source_portal": self.source_portal,
            "source_name": self.source_name,
            "source_home_url": "https://data.cityofnewyork.us/Housing-Development/DOB-Permit-Issuance/ipu4-2q9a",
            "is_live": True,
            "ingest_cadence": "daily",
            "coverage": {
                "permits": True,
                "valuation": False,     # NOT on the issuance dataset (honest gap)
                "contractor": True,
                "owner": True,          # NYC publishes owner — rare
                "phone": True,          # permittee phone
                "geocode": True,        # GIS lat/lng included
            },
        }


nyc = NYCAdapter()
register(nyc)
