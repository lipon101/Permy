from __future__ import annotations

"""Fort Worth, TX adapter — ArcGIS REST MapServer (City of Fort Worth CIVIC).

Source: mapit.fortworthtexas.gov ArcGIS "CIVIC/Permits" MapServer layer 0
("Permits"). Live, Accela-backed, point geometry.

Endpoint:
  https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/Permits/MapServer/0

Field notes (captured live 2026-07-10, 35 fields):
  Unique_ID         stable composite id
  Permit_No         "PP26-12823" / "PB26-09886"
  Permit_Type       "Plumbing" / "Electrical" / "Mechanical" / "Residential Building Permit"
                    / "Commercial Building Permit" / "Residential Accessory Struct"
                    / "Commercial Grading Permit" / "Plumbing Backflow" / "Urban Forestry"
  Permit_SubType    "Umbrella" / "General" / ...
  Address           "14457 GAME CREEK TRL"  (street only)
  Zip_Code          "76008"
  Owner_Full_Name   owner name (!) — Fort Worth publishes owner on the permit
  File_Date         epoch-ms (filed/applied)
  Status_Date       epoch-ms (last status change)
  Current_Status    "Issued" / "Open" / "Final" / ...
  JobValue          declared job value in USD (often null on small trade permits)
  Latitude          explicit decimal degrees
  Longitude         explicit decimal degrees
  B1_WORK_DESC      work description narrative
  B1_BLOCK/B1_LOT/B1_TRACT   parcel identifiers
  Use_Type / Specific_Use    occupancy
  SqFt              project square footage
  GeoCodeScore      geocode confidence 0–100

  geometry is in StatePlane TX N Central (WKID 102738 / latestWkid 2276) BUT the
  layer also publishes explicit Latitude/Longitude attribute fields in decimal
  degrees — we use those (clean WGS84) and ignore the projected geometry.

Honest gaps:
  * No contractor name on this layer (Accela contractor lives on a related table).
  * JobValue frequently null on small trade permits (plumbing/electrical) —
    populated on building permits.
"""
from typing import Any, Dict, Optional

from permy.adapters.arcgis_base import (
    ArcGISAdapter, _feature_attributes, _feature_geometry, epoch_ms_to_date,
)
from permy.adapters.base import (
    Address, ContractorRef, Enrichment, OwnerRef, Permit, PermitDates,
    _float, _int, _str, now_utc, register,
)

MAPSERVER = "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/Permits/MapServer"
LAYER_ID = 0  # "Permits"


# Permit_Type → trade
FW_TYPE_MAP = {
    "residential building permit": "building",
    "commercial building permit": "building",
    "residential accessory struct": "building",
    "commercial grading permit": "general",
    "electrical": "electrical",
    "mechanical": "hvac",
    "plumbing": "plumbing",
    "plumbing backflow": "plumbing",
    "urban forestry": "other",
}


def _trade(permit_type: Optional[str], subtype: Optional[str], work_desc: Optional[str]) -> str:
    s = " ".join(filter(None, [permit_type, subtype, work_desc])).lower()
    base = FW_TYPE_MAP.get((permit_type or "").lower())
    if base and base != "building":
        return base
    if "roof" in s:
        return "roofing"
    if "solar" in s:
        return "solar"
    if "demol" in s:
        return "demolition"
    if "new" in s and "building" in s:
        return "building"
    return base or "general"


def _work_class(permit_type: Optional[str], subtype: Optional[str], work_desc: Optional[str]) -> str:
    s = " ".join(filter(None, [permit_type, subtype, work_desc])).lower()
    if "demol" in s:
        return "demolition"
    if "new" in s and ("building" in s or "construction" in s):
        return "new_construction"
    if "addition" in s or "accessory" in s:
        return "addition"
    if "alter" in s or "remodel" in s or "repair" in s or "renov" in s:
        return "alteration"
    return "other"


def _status(current_status: Optional[str]) -> str:
    s = (current_status or "").strip().lower()
    if "issued" in s:
        return "issued"
    if "final" in s or "complete" in s or "closed" in s:
        return "final"
    if "expire" in s:
        return "expired"
    if "withdraw" in s or "cancel" in s or "void" in s:
        return "cancelled"
    if "open" in s or "active" in s or "review" in s or "pending" in s:
        return "active"
    return "unknown"


class FortWorthAdapter(ArcGISAdapter):
    jurisdiction_slug = "fortworth-tx"
    city = "Fort Worth"
    state = "TX"
    source_portal = "arcgis"
    source_name = "City of Fort Worth — Permits (mapit.fortworthtexas.gov)"
    feature_server = MAPSERVER
    layer_id = LAYER_ID
    order_field = "File_Date"

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        attrs = _feature_attributes(raw)

        source_id = _str(attrs.get("Permit_No")) or _str(attrs.get("Unique_ID")) or _str(attrs.get("CAPID"))
        permit_type = _str(attrs.get("Permit_Type"))
        subtype = _str(attrs.get("Permit_SubType"))
        work_desc = _str(attrs.get("B1_WORK_DESC"))

        street = _str(attrs.get("Address"))
        zipc = _str(attrs.get("Zip_Code"))
        full = ", ".join([x for x in [street, "Fort Worth", "TX", zipc] if x])

        # geocode: explicit Latitude/Longitude fields (decimal degrees) — clean WGS84
        lat = _float(attrs.get("Latitude"))
        lng = _float(attrs.get("Longitude"))
        geocode_conf = None
        if lat is not None and lng is not None:
            score = _int(attrs.get("GeoCodeScore"))
            geocode_conf = min(0.95, (score or 90) / 100.0) if score else 0.85

        valuation = _float(attrs.get("JobValue"))
        wc = _work_class(permit_type, subtype, work_desc)

        # owner: Fort Worth publishes Owner_Full_Name — rare and valuable
        owner = OwnerRef(name=_str(attrs.get("Owner_Full_Name")))

        # contractor: not on this layer
        contractor = None

        ts = now_utc()
        synthetic_id = f"fortworth-tx:{source_id}"

        # source_url — Fort Worth Accela public lookup
        source_url = None
        if source_id:
            source_url = f"https://accela.fortworthtexas.gov/CitizenAccess/Cap/CapHome.aspx?Module=Permits&capID1={source_id}"

        return Permit(
            id=synthetic_id,
            canonical_uid=f"fortworth-tx:{source_id}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=source_id or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street, city="Fort Worth", state="TX", zip=zipc,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=permit_type,
            permit_type_normalized=permit_type,
            work_class=wc,  # type: ignore[arg-type]
            trade_category=_trade(permit_type, subtype, work_desc),  # type: ignore[arg-type]
            is_new_construction=(wc == "new_construction"),
            is_alteration=(wc == "alteration"),
            is_demolition=(wc == "demolition"),
            valuation_usd=valuation,
            housing_units=None,
            new_add_sqft=_int(_digits_only(attrs.get("SqFt"))),
            dates=PermitDates(
                applied=epoch_ms_to_date(attrs.get("File_Date")),
                issued=epoch_ms_to_date(attrs.get("Status_Date")) if _status(attrs.get("Current_Status")) == "issued" else None,
                finaled=epoch_ms_to_date(attrs.get("Status_Date")) if _status(attrs.get("Current_Status")) == "final" else None,
                expired=None,
            ),
            current_status=_status(attrs.get("Current_Status")),  # type: ignore[arg-type]
            status_raw=_str(attrs.get("Current_Status")),
            description=work_desc,
            contractor=contractor,
            owner=owner,
            parcel_id=" ".join(filter(None, [_str(attrs.get("B1_BLOCK")), _str(attrs.get("B1_LOT"))])).strip() or None,
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        m = super().source_meta()
        m.update({
            "source_home_url": "https://mapit.fortworthtexas.gov/ags/rest/services/CIVIC/Permits/MapServer",
            "coverage": {
                "permits": True,
                "valuation": True,       # JobValue (often null on small trade permits)
                "contractor": False,     # not on this layer
                "owner": True,           # Owner_Full_Name
                "phone": False,
                "geocode": True,         # explicit Latitude/Longitude
            },
        })
        return m


def _digits_only(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = "".join(c for c in str(v) if c.isdigit() or c == ".")
    return s or None


fortworth = FortWorthAdapter()
register(fortworth)
