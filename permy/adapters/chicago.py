from __future__ import annotations

"""Chicago adapter — Socrata Open Data API (SODA).

Dataset: data.cityofchicago.org resource ydr8-5enu "Building Permits"
No auth required. Chicago publishes GIS lat/lng and up to 15 contractor
contacts per permit (contact_1..contact_15 in the full schema; the flat
Socrata API surfaces contact_1/2/3). Updated daily.

Endpoint base: https://data.cityofchicago.org/resource/ydr8-5enu.json

Honest coverage note: Chicago publishes FEES (building_fee_paid, etc.) NOT a
declared job valuation. We surface total_fee as a *fee proxy* in description
but leave valuation_usd null (fees != job value). This is flagged in coverage.
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
    _str,
    now_utc,
    register,
)
from permy.core.config import settings  # noqa: E402

RESOURCE_ID = "ydr8-5enu"
BASE_URL = f"https://data.cityofchicago.org/resource/{RESOURCE_ID}.json"


def _trade_from_fields(permit_type: Optional[str], work_type: Optional[str],
                       contact_types: List[str], description: Optional[str]) -> str:
    """Chicago trade inference."""
    s = " ".join(filter(None, [permit_type, work_type, " ".join(contact_types), description])).lower()
    if "electr" in s:
        return "electrical"
    if "plumb" in s:
        return "plumbing"
    if "mechan" in s or "hvac" in s:
        return "hvac"
    if "wrecking" in s or "demol" in s:
        return "demolition"
    if "new construction" in s:
        return "building"
    if "renovation" in s or "alteration" in s or "repair" in s:
        return "building"
    if "sign" in s:
        return "other"
    if "contractor" in s and "electrical" not in s and "plumbing" not in s:
        return "general"
    return "unknown"


def _work_class(permit_type: Optional[str]) -> str:
    s = (permit_type or "").lower()
    if "new construction" in s:
        return "new_construction"
    if "wrecking" in s or "demol" in s:
        return "demolition"
    if "renovation" in s or "alteration" in s:
        return "remodel"
    if "easy permit" in s or "express" in s:
        return "repair"
    if "sign" in s:
        return "other"
    if "porch" in s:
        return "addition"
    return "other"


def _status(permit_status: Optional[str]) -> str:
    s = (permit_status or "").strip().lower()
    return {
        "active": "active",
        "issued": "issued",
        "expired": "expired",
        "withdrawn": "withdrawn",
        "cancelled": "cancelled",
        "closed": "final",
    }.get(s, "unknown")


def _pick_contractor(raw: Dict[str, Any]) -> Optional[ContractorRef]:
    """Chicago lists up to 15 contacts. Find the primary contractor (or electrical/plumbing)."""
    # Prefer contact_1 if it's a contractor type; else scan contact_1..3
    type_priority = ("CONTRACTOR", "ELECTRICAL CONTRACTOR", "PLUMBING CONTRACTOR",
                     "MECHANICAL CONTRACTOR", "OWNER", "EXPEDITOR")
    for i in (1, 2, 3):
        ctype = _str(raw.get(f"contact_{i}_type"))
        cname = _str(raw.get(f"contact_{i}_name"))
        if not cname:
            continue
        if ctype and ctype.upper() in type_priority:
            return ContractorRef(
                name=cname,
                trade=ctype,
                phone=None,  # Chicago contacts don't include phone in the flat API
            )
    # fallback: any contact_1_name
    name1 = _str(raw.get("contact_1_name"))
    if name1:
        return ContractorRef(name=name1, trade=_str(raw.get("contact_1_type")))
    return None


def _owner(raw: Dict[str, Any]) -> OwnerRef:
    """Chicago doesn't have a clean owner field; owner appears as a contact_ type."""
    for i in (1, 2, 3):
        if (raw.get(f"contact_{i}_type") or "").upper() == "OWNER":
            return OwnerRef(name=_str(raw.get(f"contact_{i}_name")))
    return OwnerRef(name=None)


class ChicagoAdapter:
    jurisdiction_slug = "chicago-il"
    city = "Chicago"
    state = "IL"
    source_portal = "socrata"
    source_name = "City of Chicago — Building Permits (data.cityofchicago.org)"

    def __init__(self, client: Optional[httpx.Client] = None, timeout: float = 30.0):
        self._client = client or httpx.Client(timeout=timeout, headers={"Accept": "application/json"})
        if settings.socrata_app_token:
            self._client.headers["X-App-Token"] = settings.socrata_app_token

    def fetch(self, since: Optional[date] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"$limit": limit, "$order": "issue_date DESC"}
        if since is not None:
            iso = since.strftime("%Y-%m-%d")
            params["$where"] = f"issue_date >= '{iso}'"
        url = f"{BASE_URL}?{urlencode(params)}"
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        source_id = _str(raw.get("permit_")) or _str(raw.get("id"))
        permit_num = _str(raw.get("permit_"))

        # address: street_number + street_direction + street_name
        num = _str(raw.get("street_number")) or ""
        direction = _str(raw.get("street_direction")) or ""
        name = _str(raw.get("street_name")) or ""
        street_full = " ".join(p for p in [num, direction, name] if p).strip()
        full = ", ".join([x for x in [street_full, "Chicago", "IL"] if x])

        # Chicago publishes lat/lng
        lat = _float(raw.get("latitude"))
        lng = _float(raw.get("longitude"))
        geocode_conf = 0.9 if (lat is not None and lng is not None) else None

        # source_url — link to the Chicago data portal record
        source_url = None
        if source_id:
            source_url = f"https://data.cityofchicago.org/Buildings/Building-Permits/ydr8-5enu/{raw.get('id', '')}"

        permit_type = _str(raw.get("permit_type"))
        work_type = _str(raw.get("work_type"))
        wc = _work_class(permit_type)

        contact_types = [raw.get(f"contact_{i}_type") or "" for i in (1, 2, 3)]
        trade = _trade_from_fields(permit_type, work_type, contact_types,
                                   _str(raw.get("work_description")))

        contractor = _pick_contractor(raw)
        owner = _owner(raw)

        # Chicago publishes fees, not declared valuation. total_fee is a fee proxy,
        # NOT a job value — we keep valuation_usd null (honest) and put fee in description.
        total_fee = _float(raw.get("total_fee"))
        desc = _str(raw.get("work_description"))
        if total_fee is not None and total_fee > 0:
            fee_note = f" [total fees paid: ${total_fee:,.0f}]"
            desc = (desc + fee_note) if desc else fee_note.strip()

        # PIN (parcel) — Chicago publishes PIN1..PIN10; take the first non-empty
        parcel = None
        for i in range(1, 11):
            p = _str(raw.get(f"pin{i}") or raw.get(f"PIN{i}"))
            if p:
                parcel = p
                break

        ts = now_utc()
        synthetic_id = f"chicago-il:{source_id}"

        return Permit(
            id=synthetic_id,
            canonical_uid=f"chicago-il:{source_id}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=source_id or permit_num or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street_full or None, city="Chicago", state="IL", zip=None,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=permit_num or permit_type,
            permit_type_normalized=permit_type,  # Chicago's permit_type is already human-readable
            work_class=wc,  # type: ignore[arg-type]
            trade_category=trade,  # type: ignore[arg-type]
            is_new_construction=(wc == "new_construction"),
            is_alteration=(wc in ("remodel", "addition", "repair")),
            is_demolition=(wc == "demolition"),
            valuation_usd=None,  # honest: Chicago publishes fees, not valuation
            housing_units=None,
            new_add_sqft=None,
            dates=PermitDates(
                applied=_date(raw.get("application_start_date")),
                issued=_date(raw.get("issue_date")),
                finaled=None, expired=None,
            ),
            current_status=_status(raw.get("permit_status")),  # type: ignore[arg-type]
            status_raw=_str(raw.get("permit_status")),
            description=desc,
            contractor=contractor,
            owner=owner,
            parcel_id=parcel,
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        return {
            "jurisdiction_slug": self.jurisdiction_slug,
            "city": self.city,
            "state": self.state,
            "source_portal": self.source_portal,
            "source_name": self.source_name,
            "source_home_url": "https://data.cityofchicago.org/Buildings/Building-Permits/ydr8-5enu",
            "is_live": True,
            "ingest_cadence": "daily",
            "coverage": {
                "permits": True,
                "valuation": False,    # fees, not declared job value (honest gap)
                "contractor": True,    # contact_1..15
                "owner": "partial",    # owner only if listed as a contact
                "phone": False,        # Chicago contacts lack phone in flat API
                "geocode": True,       # lat/lng included
            },
        }


chicago = ChicagoAdapter()
register(chicago)
