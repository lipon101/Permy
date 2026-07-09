from __future__ import annotations

"""Los Angeles, CA adapter — LADBS ArcGIS REST FeatureServer.

Source: Los Angeles Dept of Building & Safety permit activity published via an
ArcGIS FeatureServer. Layer 2 "All Building" is the comprehensive permits layer
(72 fields).

Endpoint: https://lacitydbs.org/arcgiswebad/rest/services/PERMIT_FC_PRO/FeatureServer/2

LA publishes, unusually for ArcGIS, explicit LAT/LON attribute fields in decimal
degrees — so geocoding is clean even though the feature ``geometry`` is in a
projected StatePlane CRS (WKID 2229). We prefer LAT/LON and ignore the projected
geometry.

Field notes (captured live 2026-07-09, 72 fields):
  ADDRESS          "7366 N HAYVENHURST AVE, 91406" (street + zip baked together)
  PER_TYPE         "Bldg-New" / "Bldg-Alter/Repair" / "Bldg-Demolition" / "Elec-*" / "Mech-*" / "Plumb-*"
  PER_SUB_TYPE     "Commercial" / "Residential" / "1 or 2 Family Dwelling"
  STATUS_DESC      human status ("Issued", "Reviewed by Supervisor", "Permit Finaled", ...)
  FILE_DATE        epoch-ms (application/filed)
  ISSUE_DATE       epoch-ms (issued) — often null on recent in-review records
  FINAL_DATE       epoch-ms (finalled)
  COFO_DATE        epoch-ms (certificate of occupancy)
  VALUATION        declared job value in USD
  USE_CODE / USE_DESC  occupancy class
  DU_TOTAL         dwelling units
  STORIES          building stories
  TYPE_OF_CONST    construction type
  NHOOD            neighborhood

Honest gaps:
  * No contractor name on the main feature (license-board join later via CA CSLB).
  * Owner not published.
"""
from typing import Any, Dict, Optional

from permy.adapters.arcgis_base import (
    ArcGISAdapter, _feature_attributes, _feature_geometry, epoch_ms_to_date,
)
from permy.adapters.base import (
    Address, ContractorRef, Enrichment, OwnerRef, Permit, PermitDates,
    _float, _int, _str, now_utc, register,
)

FEATURE_SERVER = "https://lacitydbs.org/arcgiswebad/rest/services/PERMIT_FC_PRO/FeatureServer"
LAYER_ID = 2  # "All Building"


def _trade_from_per_type(per_type: Optional[str], per_sub: Optional[str],
                         use_desc: Optional[str]) -> str:
    """LA PER_TYPE is prefixed by trade: 'Bldg-*', 'Elec-*', 'Mech-*', 'Plumb-*'."""
    s = " ".join(filter(None, [per_type, per_sub, use_desc])).lower()
    if "elec" in s:
        return "electrical"
    if "mech" in s or "hvac" in s:
        return "hvac"
    if "plumb" in s:
        return "plumbing"
    if "demol" in s:
        return "demolition"
    if "bldg-new" in s or "new construction" in s:
        return "building"
    if "bldg-alter" in s or "alter" in s or "repair" in s:
        return "general"
    if "bldg" in s:
        return "building"
    return "unknown"


def _work_class_from_per_type(per_type: Optional[str]) -> str:
    s = (per_type or "").strip().lower()
    if "bldg-new" in s:
        return "new_construction"
    if "bldg-demol" in s or "demolition" in s:
        return "demolition"
    if "bldg-alter" in s or "alter" in s or "repair" in s:
        return "alteration"
    if "bldg-add" in s or "addition" in s:
        return "addition"
    return "other"


def _status(status_desc: Optional[str]) -> str:
    s = (status_desc or "").strip().lower()
    if "issued" in s and "not issued" not in s:
        return "issued"
    if "finaled" in s or "c of o" in s or "cofo" in s:
        return "final"
    if "expire" in s:
        return "expired"
    if "withdraw" in s or "cancel" in s or "void" in s:
        return "cancelled"
    if "review" in s or "submit" in s or "pending" in s or "intake" in s:
        return "applied"
    if "active" in s or "in progress" in s:
        return "active"
    return "unknown"


class LAAdapter(ArcGISAdapter):
    jurisdiction_slug = "la-ca"
    city = "Los Angeles"
    state = "CA"
    source_portal = "arcgis"
    source_name = "LA Dept of Building & Safety — Permits (lacitydbs.org)"
    feature_server = FEATURE_SERVER
    layer_id = LAYER_ID
    order_field = "FILE_DATE"  # ISSUE_DATE often null on recent records

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        attrs = _feature_attributes(raw)
        geom = _feature_geometry(raw)

        # source id — OBJECTID is stable + unique within the layer
        source_id = _str(attrs.get("PCIS_ID")) or _str(attrs.get("OBJECTID"))
        object_id = _str(attrs.get("OBJECTID"))

        # ADDRESS is "7366 N HAYVENHURST AVE, 91406" — split street + zip
        addr_full = _str(attrs.get("ADDRESS")) or ""
        street = None
        zipc = None
        if addr_full:
            parts = [p.strip() for p in addr_full.split(",")]
            street = parts[0] or None
            if len(parts) > 1:
                # last part is usually the ZIP
                tail = parts[-1].strip()
                if tail.isdigit() and len(tail) == 5:
                    zipc = tail
                elif len(parts) > 2 and parts[-1].isdigit():
                    zipc = parts[-1]
                elif len(parts) >= 2 and parts[-1].replace(" ", "").isdigit():
                    zipc = parts[-1].strip()

        # geocode: LA publishes explicit LAT/LON attribute fields (decimal degrees)
        lat = _float(attrs.get("LAT"))
        lng = _float(attrs.get("LON"))
        geocode_conf = 0.9 if (lat is not None and lng is not None) else None

        per_type = _str(attrs.get("PER_TYPE"))
        per_sub = _str(attrs.get("PER_SUB_TYPE"))
        use_desc = _str(attrs.get("USE_DESC"))
        work_class = _work_class_from_per_type(per_type)
        trade = _trade_from_per_type(per_type, per_sub, use_desc)

        valuation = _float(attrs.get("VALUATION"))

        ts = now_utc()
        synthetic_id = f"la-ca:{source_id}"

        # source_url: LADBS public record lookup (PCIS-based when available)
        source_url = None
        if _str(attrs.get("PCIS_ID")):
            source_url = f"https://www.ladbs.org/services/checkpermit-status?pcis_id={attrs.get('PCIS_ID')}"

        # no contractor on the main LA feature; owner not published
        contractor = None
        owner = OwnerRef(name=None)

        full = ", ".join([x for x in [street, "Los Angeles", "CA", zipc] if x])

        return Permit(
            id=synthetic_id,
            canonical_uid=f"la-ca:{source_id}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=source_id or object_id or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street, city="Los Angeles", state="CA", zip=zipc,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=per_type,
            permit_type_normalized=(per_type.replace("Bldg-", "Building — ").replace("Elec-", "Electrical — ").replace("Mech-", "Mechanical — ").replace("Plumb-", "Plumbing — ") if per_type else None),
            work_class=work_class,  # type: ignore[arg-type]
            trade_category=trade,  # type: ignore[arg-type]
            is_new_construction=(work_class == "new_construction"),
            is_alteration=(work_class == "alteration"),
            is_demolition=(work_class == "demolition"),
            valuation_usd=valuation,
            housing_units=_int(attrs.get("DU_TOTAL")),
            new_add_sqft=None,
            dates=PermitDates(
                applied=epoch_ms_to_date(attrs.get("FILE_DATE")),
                issued=epoch_ms_to_date(attrs.get("ISSUE_DATE")),
                finaled=epoch_ms_to_date(attrs.get("FINAL_DATE")) or epoch_ms_to_date(attrs.get("COFO_DATE")),
                expired=None,
            ),
            current_status=_status(attrs.get("STATUS_DESC")),  # type: ignore[arg-type]
            status_raw=_str(attrs.get("STATUS_DESC")),
            description=_str(attrs.get("WORK_DESC")) or use_desc,
            contractor=contractor,
            owner=owner,
            parcel_id=None,  # LA has a PARCEL layer but not on the permit feature
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        m = super().source_meta()
        m.update({
            "source_home_url": "https://www.lacitydbs.org/",
            "coverage": {
                "permits": True,
                "valuation": True,      # VALUATION declared job value
                "contractor": False,    # not on main feature; CSLB join later
                "owner": False,
                "phone": False,
                "geocode": True,        # explicit LAT/LON fields
            },
        })
        return m


la = LAAdapter()
register(la)
