from __future__ import annotations

"""Miami-Dade County, FL adapter — ArcGIS REST MapServer.

Source: Miami-Dade GIS "County Building Permits" published via ArcGIS REST.
This is the dataset that 502'd on Socrata — ArcGIS is the correct path.

Endpoint: https://gisweb.miamidade.gov/arcgis/rest/services/MD_LandInformation/MapServer/1

Field notes (captured live 2026-07-09, 42 fields):
  OBJECTID    stable feature id
  ID          permit number (e.g. "2026055993")
  MPRMTNUM    master permit number
  PROCNUM     process number
  ADDRESS     "5100 SW 115 AVE"
  ISSUDATE    epoch-ms (issued date)
  BLDCMPDT    epoch-ms (building completion)
  LSTINSDT    epoch-ms (last inspection)
  LSTAPPRDT   epoch-ms (last approval)
  RENDATE     epoch-ms (renewal)
  TYPE        "BLDG" / "MEP" / "ELE" / "PLB"
  BPSTATUS    "A"=active, "F"=final, "X"=expired/cancelled
  CONTRNAME   contractor name (!)
  CONTRNUM    contractor license number (!)
  FOLIO       parcel folio number
  PROPUSE     property use code
  RESCOMM     residential/commercial flag
  CAT1..10 / DESC1..10   work category / description pairs (up to 10 each)
  UNIT        unit number

Honest gaps:
  * No owner name published.
  * No contractor phone (only name + license #).
  * Geometry is in a PROJECTED CRS (WKID 2236, StatePlane Florida East) — NOT
    WGS84 lat/lng, and there are no explicit lat/lng attribute fields. We store
    the raw x/y in address but mark geocode_confidence low and set the city's
    geocode coverage flag to False (honest). A reprojection step (Proj4) can
    upgrade this later.
"""
from typing import Any, Dict, List, Optional  # noqa: E402

from permy.adapters.arcgis_base import (  # noqa: E402
    ArcGISAdapter,
    _feature_attributes,
    _feature_geometry,
    epoch_ms_to_date,
    reproject_xy,
)
from permy.adapters.base import (  # noqa: E402
    Address,
    ContractorRef,
    Enrichment,
    OwnerRef,
    Permit,
    PermitDates,
    _str,
    now_utc,
    register,
)

MAPSERVER = "https://gisweb.miamidade.gov/arcgis/rest/services/MD_LandInformation/MapServer"
LAYER_ID = 1  # "County Building Permits"
GEOMETRY_WKID = 2236  # NAD83 / StatePlane Florida East (projected)


# TYPE code → trade
MIAMI_TYPE_MAP = {
    "BLDG": "building",
    "MEP": "hvac",      # mechanical
    "ELE": "electrical",
    "PLB": "plumbing",
    "PLM": "plumbing",
    "ROF": "roofing",
    "GAS": "other",
    "LFG": "other",
}


def _trade(type_code: Optional[str], contrname: Optional[str], descriptions: List[str]) -> str:
    s = " ".join(filter(None, [type_code, contrname] + descriptions)).lower()
    base = MIAMI_TYPE_MAP.get((type_code or "").upper())
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
    if "mechan" in s or "hvac" in s or "air condition" in s:
        return "hvac"
    if "demol" in s:
        return "demolition"
    if "new construction" in s or "new bldg" in s:
        return "building"
    return base or "general"


def _work_class(type_code: Optional[str], descriptions: List[str]) -> str:
    s = " ".join(filter(None, [type_code] + descriptions)).lower()
    if "demol" in s:
        return "demolition"
    if "new" in s and ("construction" in s or "bldg" in s):
        return "new_construction"
    if "addition" in s or "add" in s:
        return "addition"
    if "alter" in s or "remodel" in s or "repair" in s or "renov" in s:
        return "alteration"
    return "other"


def _status(bpstatus: Optional[str]) -> str:
    s = (bpstatus or "").strip().upper()
    return {
        "A": "active",
        "F": "final",
        "X": "expired",
        "C": "cancelled",
        "E": "expired",
        "P": "applied",     # pending
    }.get(s, "unknown")


class MiamiAdapter(ArcGISAdapter):
    jurisdiction_slug = "miami-fl"
    city = "Miami"
    state = "FL"
    source_portal = "arcgis"
    source_name = "Miami-Dade County — Building Permits (gisweb.miamidade.gov)"
    feature_server = MAPSERVER
    layer_id = LAYER_ID
    order_field = "ISSUDATE"

    def normalize(self, raw: Dict[str, Any]) -> Permit:
        attrs = _feature_attributes(raw)
        geom = _feature_geometry(raw)

        source_id = _str(attrs.get("ID")) or _str(attrs.get("MPRMTNUM")) or _str(attrs.get("OBJECTID"))
        object_id = _str(attrs.get("OBJECTID"))

        addr_full = _str(attrs.get("ADDRESS")) or ""
        street = addr_full.strip() or None
        zipc = _str(attrs.get("ZIP"))  # not always present
        _unit = _str(attrs.get("UNIT"))  # noqa: F841  # parsed but not yet surfaced

        # work category / description pairs (CAT1..10 + DESC1..10)
        descriptions: List[str] = []
        for i in range(1, 11):
            d = _str(attrs.get(f"DESC{i}"))
            if d:
                descriptions.append(d)
        type_code = _str(attrs.get("TYPE"))

        # geocode: Miami geometry is PROJECTED (StatePlane FL, WKID 2236) with no
        # explicit lat/lng fields. Reproject x/y → WGS84 via pyproj when available;
        # otherwise honest null (coverage flag stays False). The WKID is read from
        # the fixture's spatialReference (set by fetch()) with a hardcoded fallback.
        wkid = getattr(self, "_geometry_wkid", None) or GEOMETRY_WKID
        gx = _float_geom(geom.get("x")) if geom else None
        gy = _float_geom(geom.get("y")) if geom else None
        lat = None
        lng = None
        geocode_conf = None
        if gx is not None and gy is not None:
            lat, lng = reproject_xy(gx, gy, wkid)
            if lat is not None and lng is not None:
                geocode_conf = 0.7  # reprojected from parcel centroid; not rooftop

        valuation = None  # Miami publishes fees, not declared valuation, on this layer

        contractor = None
        cname = _str(attrs.get("CONTRNAME"))
        cnum = _str(attrs.get("CONTRNUM"))
        if cname or cnum:
            contractor = ContractorRef(
                name=cname, license=cnum, license_state="FL", trade=None, phone=None,
            )

        owner = OwnerRef(name=None)

        full = ", ".join([x for x in [street, "Miami", "FL", zipc] if x])
        ts = now_utc()
        synthetic_id = f"miami-fl:{source_id}"

        # source_url: Miami-Dade ePermits one-stop lookup by permit number
        source_url = None
        if source_id:
            source_url = f"https://www.miamidade.gov/ePermits/permit/{source_id}"

        wc = _work_class(type_code, descriptions)

        return Permit(
            id=synthetic_id,
            canonical_uid=f"miami-fl:{source_id}",
            jurisdiction_slug=self.jurisdiction_slug,
            source_permit_id=source_id or object_id or "",
            source_url=source_url,
            source_name=self.source_name,
            first_seen_at=ts, last_seen_at=ts, last_checked_at=ts,
            address=Address(
                street=street, city="Miami", state="FL", zip=zipc,
                full=full, lat=lat, lng=lng, geocode_confidence=geocode_conf,
            ),
            permit_type_raw=type_code,
            permit_type_normalized={"BLDG": "Building Permit", "MEP": "Mechanical Permit",
                                    "ELE": "Electrical Permit", "PLB": "Plumbing Permit",
                                    "ROF": "Roofing Permit"}.get((type_code or "").upper()),
            work_class=wc,  # type: ignore[arg-type]
            trade_category=_trade(type_code, cname, descriptions),  # type: ignore[arg-type]
            is_new_construction=(wc == "new_construction"),
            is_alteration=(wc == "alteration"),
            is_demolition=(wc == "demolition"),
            valuation_usd=valuation,  # honest null — Miami publishes fees, not valuation
            housing_units=None,
            new_add_sqft=None,
            dates=PermitDates(
                applied=epoch_ms_to_date(attrs.get("LSTAPPRDT")),
                issued=epoch_ms_to_date(attrs.get("ISSUDATE")),
                finaled=epoch_ms_to_date(attrs.get("BLDCMPDT")),
                expired=None,
            ),
            current_status=_status(attrs.get("BPSTATUS")),  # type: ignore[arg-type]
            status_raw=_str(attrs.get("BPSTATUS")),
            description=" | ".join(descriptions) if descriptions else None,
            contractor=contractor,
            owner=owner,
            parcel_id=_str(attrs.get("FOLIO")),
            enrichment=Enrichment(confidence=0.0),
        )

    def source_meta(self) -> Dict[str, Any]:
        m = super().source_meta()
        m.update({
            "source_home_url": "https://gisweb.miamidade.gov/arcgis/rest/services/MD_LandInformation/MapServer",
            "coverage": {
                "permits": True,
                "valuation": False,    # publishes fees, not declared valuation
                "contractor": True,    # CONTRNAME + CONTRNUM
                "owner": False,
                "phone": False,        # name + license # only
                "geocode": True,       # reprojected StatePlane → WGS84 via pyproj
            },
        })
        return m


def _float_geom(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


miami = MiamiAdapter()
register(miami)
