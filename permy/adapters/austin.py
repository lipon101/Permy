from __future__ import annotations

"""Austin, TX adapter — Socrata Open Data API (SODA).

Dataset: data.austintexas.gov resource 3syk-w9eu "Building Permits"
No auth required for public reads (optional app token raises the anon rate limit).
Richest municipal permit schema we've seen published openly: includes contractor phone.

Endpoint base: https://data.austintexas.gov/resource/3syk-w9eu.json
SoQL params used: $limit, $order, $where (for incremental pulls), $select (rare).
"""
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from permy.adapters.base import (
    Address, ContractorRef, Enrichment, OwnerRef, Permit, PermitDates,
    _date, _float, _int, _str, now_utc, register,
)
from permy.core.config import AUSTIN_PERMITTYPE_MAP, AUSTIN_WORKCLASS_MAP, settings

RESOURCE_ID = "3syk-w9eu"
BASE_URL = f"https://data.austintexas.gov/resource/{RESOURCE_ID}.json"


def _trade_from_fields(permit_type_desc: Optional[str], trade_field: Optional[str], description: Optional[str]) -> str:
    """Map Austin's trade signals → canonical trade_category.

    Austin publishes contractor_trade ('Electrical Contractor', 'Mechanical Contractor', ...)
    plus permit_type_desc. We prefer the explicit trade; fall back to keywords in the description.
    Classification refinement by the shared classifier happens later — this is a first cut.
    """
    s = " ".join(filter(None, [trade_field, permit_type_desc, description])).lower()
    if "electr" in s:
        return "electrical"
    if "mechan" in s or "hvac" in s:
        return "hvac"
    if "plumb" in s:
        return "plumbing"
    if "roof" in s:
        return "roofing"
    if "solar" in s:
        return "solar"
    if "demol" in s:
        return "demolition"
    if "building" in s or "new construction" in s:
        return "building"
    if "contractor" in s or "builder" in s:
        return "general"
    return "unknown"


def _work_class(raw_work: Optional[str]) -> str:
    if not raw_work:
        return "unknown"
    key = raw_work.strip().lower()
    return AUSTIN_WORKCLASS_MAP.get(key, "other")


def _status(status_current: Optional[str]) -> str:
    s = (status_current or "").strip().lower()
    return {
        "active": "active",
        "final": "final",
        "expired": "expired",
        "withdrawn": "withdrawn",
        "cancelled": "cancelled",
        "open": "applied",
    }.get(s, "unknown")


class AustinAdapter:
    jurisdiction_slug = "austin-tx"
    city = "Austin"
    state = "TX"
    source_portal = "socrata"
    source_name = "City of Austin — Building Permits (data.austintexas.gov)"

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        if settings.socrata_app_token:
            self._client.headers["X-App-Token"] = settings.socrata_app_token

    # ---- fetch ----
    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"$limit": limit, "$order": "issue_date DESC"}
        if since is not None:
            # SoQL date filter
            iso = since.strftime("%Y-%m-%d")
            params["$where"] = f"issue_date >= '{iso}'"
        url = f"{BASE_URL}?{urlencode(params)}"
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    # ---- normalize ----
    def normalize(self, raw: Dict[str, Any]) -> Permit:
        project_id = _str(raw.get("project_id")) or _str(raw.get("permit_number"))
        permit_num = _str(raw.get("permit_number"))
        ptype_code = _str(raw.get("permittype"))
        permit_type_desc = _str(raw.get("permit_type_desc"))

        street = _str(raw.get("original_address1")) or _str(raw.get("permit_location"))
        city = _str(raw.get("original_city")) or "Austin"
        state = _str(raw.get("original_state")) or "TX"
        zipc = _str(raw.get("original_zip"))

        # Austin provides a hardlink to the public permit detail page — provenance gold.
        link = raw.get("link")
        source_url = None
        if isinstance(link, dict):
            source_url = _str(link.get("url"))
        elif isinstance(link, str):
            source_url = link
        if not source_url and project_id:
            source_url = (
                "https://abc.austintexas.gov/web/permit/public-search-other"
                f"?t_detail=1&t_selected_folderrsn={project_id}"
            )

        # contractor
        contractor = None
        if _str(raw.get("contractor_company_name")) or _str(raw.get("contractor_full_name")):
            contractor = ContractorRef(
                name=_str(raw.get("contractor_company_name")) or _str(raw.get("contractor_full_name")),
                license=None,  # Austin doesn't publish license # on the permit record; join via TX TRCC later
                trade=_str(raw.get("contractor_trade")),
                phone=_str(raw.get("contractor_phone")),
            )

        work_raw = _str(raw.get("work_class"))
        work_class = _work_class(work_raw)
        trade = _trade_from_fields(permit_type_desc, _str(raw.get("contractor_trade")), _str(raw.get("description")))

        # Austin valuation lives on the commercial record; residential often null.
        valuation = _float(raw.get("total_job_valuation")) or _float(raw.get("declared_valuation"))
        if valuation is None:
            # Some Austin rows carry it as "TotalJobValuation"
            valuation = _float(raw.get("TotalJobValuation"))

        ts = now_utc()
        # build a Permit (id assigned at insert; we set a synthetic id from project_id for the
        # normalized in-memory form; the DB assigns a real bigint id on insert)
        synthetic_id = f"austin-tx:{project_id}"

        return Permit(
            id=synthetic_id,
            canonical_uid=f"austin-tx:{project_id}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=project_id or permit_num or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts,
            last_seen_at=ts,
            last_checked_at=ts,
            address=Address(
                street=street,
                city=city,
                state=state,
                zip=zipc,
                full=", ".join([x for x in [street, city, state, zipc] if x]),
            ),
            permit_type_raw=permit_num or ptype_code,
            permit_type_normalized=AUSTIN_PERMITTYPE_MAP.get(ptype_code or "", permit_type_desc),
            work_class=work_class,  # type: ignore[arg-type]
            trade_category=trade,  # type: ignore[arg-type]
            is_new_construction=(work_class == "new_construction"),
            is_alteration=(work_class in ("alteration", "remodel", "addition")),
            is_demolition=(work_class == "demolition"),
            valuation_usd=valuation,
            housing_units=_int(raw.get("housing_units")),
            new_add_sqft=_int(raw.get("total_new_add_sqft")),
            dates=PermitDates(
                applied=_date(raw.get("applieddate")),
                issued=_date(raw.get("issue_date")),
                finaled=_date(raw.get("completed_date")),
                expired=_date(raw.get("expiresdate")),
            ),
            current_status=_status(raw.get("status_current")),  # type: ignore[arg-type]
            status_raw=_str(raw.get("status_current")),
            description=_str(raw.get("description")),
            contractor=contractor,
            owner=OwnerRef(name=None),  # Austin doesn't publish owner name on permits
            parcel_id=_str(raw.get("tcad_id")),
            enrichment=Enrichment(confidence=0.0),  # filled by pipeline after geocode+score
        )

    # ---- coverage meta ----
    def source_meta(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "city": self.city,
            "state": self.state,
            "source_portal": self.source_portal,
            "source_name": self.source_name,
            "source_home_url": "https://data.austintexas.gov/Permitting/Building-Permits/3syk-w9eu",
            "is_live": True,
            "ingest_cadence": "daily",
            "coverage": {
                "permits": True,
                "valuation": True,      # present but often null on residential
                "contractor": True,
                "owner": False,
                "phone": True,          # Austin is unusually generous here
                "geocode": False,       # no lat/lng in feed; we geocode downstream
            },
        }


austin = AustinAdapter()
register(austin)
