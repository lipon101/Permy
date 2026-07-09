from __future__ import annotations

"""Tests for the 4 new city adapters (SF, Seattle, LA, Miami) + ArcGIS base.

Each adapter normalizes its recorded REAL fixture (captured live, no network in
CI) into the canonical Permit shape. The cross-city test at the bottom proves
ALL 7 cities — Socrata + ArcGIS — normalize into the same Permit schema, which
is Permy's core differentiator.
"""
import json  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

FX = Path(__file__).parent / "fixtures"


def _load(slug: str, arcgis: bool):
    d = json.loads((FX / slug / "sample_3.json").read_text())
    return d["features"] if arcgis else d


# ---- ArcGIS base helpers ----
def test_epoch_ms_to_date_valid():
    from permy.adapters.arcgis_base import epoch_ms_to_date
    assert epoch_ms_to_date(1782950400000) == date(2026, 7, 2)  # Miami ISSUDATE


def test_epoch_ms_to_date_handles_sentinels():
    from permy.adapters.arcgis_base import epoch_ms_to_date
    # Miami uses "00000000" and epoch 0 as "no date"
    assert epoch_ms_to_date("00000000") is None
    assert epoch_ms_to_date(0) is None
    assert epoch_ms_to_date(None) is None
    assert epoch_ms_to_date("") is None


def test_epoch_ms_to_date_iso_string():
    from permy.adapters.arcgis_base import epoch_ms_to_date
    assert epoch_ms_to_date("2026-07-08T00:00:00.000") == date(2026, 7, 8)


def test_reproject_xy_miami_stateplane():
    from permy.adapters.arcgis_base import reproject_xy
    # Miami sample geometry, StatePlane FL East (WKID 2236) -> WGS84
    lat, lng = reproject_xy(859862.1874304265, 504169.1564017683, 2236)
    assert lat is not None and lng is not None
    assert 25.0 < lat < 26.5     # Miami-Dade latitude band
    assert -81.0 < lng < -80.0   # Miami-Dade longitude band


def test_reproject_xy_none_inputs():
    from permy.adapters.arcgis_base import reproject_xy
    assert reproject_xy(None, 1.0, 2236) == (None, None)
    assert reproject_xy(1.0, None, 2236) == (None, None)
    assert reproject_xy(1.0, 2.0, None) == (None, None)


def test_feature_attributes_unwrap():
    from permy.adapters.arcgis_base import _feature_attributes
    feat = {"attributes": {"ID": "123"}, "geometry": {"x": 1}}
    assert _feature_attributes(feat) == {"ID": "123"}
    # plain dict (no attributes key) → returned as-is
    assert _feature_attributes({"ID": "123"}) == {"ID": "123"}


# ---- SF ----
def test_sf_normalize_basic():
    from permy.adapters.sf import SFAdapter
    rows = _load("sf", arcgis=False)
    a = SFAdapter()
    p = a.normalize(rows[0])
    assert p.jurisdiction_slug == "sf-ca"
    assert p.address.city == "San Francisco"
    assert p.address.state == "CA"
    assert p.source_permit_id  # permit_number populated
    assert p.canonical_uid == f"sf-ca:{p.source_permit_id}"


def test_sf_geocode_from_geojson_location():
    from permy.adapters.sf import SFAdapter
    rows = _load("sf", arcgis=False)
    p = SFAdapter().normalize(rows[0])
    # SF publishes GeoJSON Point {coordinates:[lng,lat]}
    assert p.address.lat is not None and p.address.lng is not None
    assert 37.0 < p.address.lat < 38.0    # SF latitude
    assert -123.0 < p.address.lng < -122.0
    assert p.address.geocode_confidence == 0.95


def test_sf_valuation_revised_over_estimated():
    from permy.adapters.sf import SFAdapter
    rows = _load("sf", arcgis=False)
    p = SFAdapter().normalize(rows[0])
    # revised_cost is preferred when present
    assert p.valuation_usd is not None
    assert p.valuation_usd > 0


def test_sf_no_contractor_or_owner_honest_nulls():
    from permy.adapters.sf import SFAdapter
    rows = _load("sf", arcgis=False)
    p = SFAdapter().normalize(rows[0])
    assert p.contractor is None        # not on DBI main record
    assert p.owner is not None and p.owner.name is None


def test_sf_source_meta_honest_flags():
    from permy.adapters.sf import SFAdapter
    m = SFAdapter().source_meta()
    assert m["coverage"]["valuation"] is True
    assert m["coverage"]["contractor"] is False
    assert m["coverage"]["owner"] is False
    assert m["coverage"]["geocode"] is True
    assert m["source_portal"] == "socrata"


# ---- Seattle ----
def test_seattle_normalize_basic():
    from permy.adapters.seattle import SeattleAdapter
    rows = _load("seattle", arcgis=False)
    p = SeattleAdapter().normalize(rows[0])
    assert p.jurisdiction_slug == "seattle-wa"
    assert p.address.city is not None
    assert p.canonical_uid == f"seattle-wa:{p.source_permit_id}"


def test_seattle_geocode_lat_lng_fields():
    from permy.adapters.seattle import SeattleAdapter
    rows = _load("seattle", arcgis=False)
    p = SeattleAdapter().normalize(rows[0])
    assert p.address.lat is not None and p.address.lng is not None
    assert 47.0 < p.address.lat < 48.0     # Seattle latitude
    assert -123.0 < p.address.lng < -122.0


def test_seattle_valuation_estprojectcost():
    from permy.adapters.seattle import SeattleAdapter
    rows = _load("seattle", arcgis=False)
    p = SeattleAdapter().normalize(rows[0])
    assert p.valuation_usd is not None and p.valuation_usd > 0


def test_seattle_demolition_trade():
    from permy.adapters.seattle import SeattleAdapter
    rows = _load("seattle", arcgis=False)
    # first fixture is a demolition permit
    p = SeattleAdapter().normalize(rows[0])
    assert p.trade_category == "demolition"
    assert p.is_demolition is True


def test_seattle_no_contractor_honest():
    from permy.adapters.seattle import SeattleAdapter
    rows = _load("seattle", arcgis=False)
    a = SeattleAdapter()
    p = a.normalize(rows[0])
    assert p.contractor is None
    assert a.source_meta()["coverage"]["contractor"] is False


# ---- LA (ArcGIS) ----
def test_la_normalize_basic():
    from permy.adapters.la import LAAdapter
    rows = _load("la", arcgis=True)
    a = LAAdapter()
    p = a.normalize(rows[0])
    assert p.jurisdiction_slug == "la-ca"
    assert p.address.state == "CA"
    assert p.source_permit_id
    assert p.canonical_uid == f"la-ca:{p.source_permit_id}"


def test_la_geocode_lat_lon_fields():
    from permy.adapters.la import LAAdapter
    rows = _load("la", arcgis=True)
    p = LAAdapter().normalize(rows[0])
    # LA publishes explicit LAT/LON attribute fields (decimal degrees)
    assert p.address.lat is not None and p.address.lng is not None
    assert 33.0 < p.address.lat < 35.0     # LA latitude band
    assert -119.0 < p.address.lng < -118.0


def test_la_valuation_present():
    from permy.adapters.la import LAAdapter
    rows = _load("la", arcgis=True)
    p = LAAdapter().normalize(rows[0])
    assert p.valuation_usd is not None and p.valuation_usd > 0


def test_la_epoch_ms_dates_parsed():
    from permy.adapters.la import LAAdapter
    rows = _load("la", arcgis=True)
    p = LAAdapter().normalize(rows[0])
    # FILE_DATE is epoch-ms; should parse to a real date (not 1970)
    assert p.dates.applied is not None
    assert p.dates.applied.year > 2000


def test_la_address_zip_split():
    from permy.adapters.la import LAAdapter
    rows = _load("la", arcgis=True)
    p = LAAdapter().normalize(rows[0])
    # ADDRESS is "7366 N HAYVENHURST AVE, 91406" — zip should split off
    assert p.address.zip is not None
    assert len(p.address.zip) == 5
    assert p.address.street is not None


def test_la_no_contractor_honest():
    from permy.adapters.la import LAAdapter
    m = LAAdapter().source_meta()
    assert m["coverage"]["contractor"] is False
    assert m["source_portal"] == "arcgis"


# ---- Miami (ArcGIS, projected geometry reprojected) ----
def test_miami_normalize_basic():
    from permy.adapters.miami import MiamiAdapter
    rows = _load("miami", arcgis=True)
    a = MiamiAdapter()
    a._geometry_wkid = 2236
    p = a.normalize(rows[0])
    assert p.jurisdiction_slug == "miami-fl"
    assert p.source_permit_id
    assert p.canonical_uid == f"miami-fl:{p.source_permit_id}"


def test_miami_geometry_reprojected_to_wgs84():
    from permy.adapters.miami import MiamiAdapter
    rows = _load("miami", arcgis=True)
    a = MiamiAdapter()
    a._geometry_wkid = 2236
    p = a.normalize(rows[0])
    # Miami geometry is StatePlane; reprojected to WGS84 via pyproj
    assert p.address.lat is not None and p.address.lng is not None
    assert 25.0 < p.address.lat < 26.5      # Miami-Dade latitude
    assert -81.0 < p.address.lng < -80.0


def test_miami_contractor_name_and_license():
    from permy.adapters.miami import MiamiAdapter
    rows = _load("miami", arcgis=True)
    a = MiamiAdapter()
    a._geometry_wkid = 2236
    # first fixture is G&R ROOFING LLC
    p = a.normalize(rows[0])
    assert p.contractor is not None
    assert p.contractor.name is not None
    assert "ROOFING" in p.contractor.name.upper()
    assert p.contractor.license is not None      # CONTRNUM
    assert p.contractor.license_state == "FL"


def test_miami_valuation_honest_null():
    from permy.adapters.miami import MiamiAdapter
    rows = _load("miami", arcgis=True)
    a = MiamiAdapter()
    a._geometry_wkid = 2236
    p = a.normalize(rows[0])
    # Miami publishes fees, not declared valuation → honest null
    assert p.valuation_usd is None
    assert a.source_meta()["coverage"]["valuation"] is False


def test_miami_sentinel_dates_are_null():
    from permy.adapters.miami import MiamiAdapter
    rows = _load("miami", arcgis=True)
    a = MiamiAdapter()
    a._geometry_wkid = 2236
    p = a.normalize(rows[0])
    # LSTAPPRDT/BLDCMPDT are "00000000" → must be None, not 1970-01-01
    assert p.dates.applied is None
    assert p.dates.finaled is None
    # ISSUDATE is a real epoch-ms → populated
    assert p.dates.issued is not None
    assert p.dates.issued.year == 2026


def test_miami_parcel_folio():
    from permy.adapters.miami import MiamiAdapter
    rows = _load("miami", arcgis=True)
    a = MiamiAdapter()
    a._geometry_wkid = 2236
    p = a.normalize(rows[0])
    assert p.parcel_id is not None      # FOLIO


# ---- cross-city: ALL 7 cities normalize to the same Permit shape ----
def test_all_seven_cities_produce_valid_permits():
    """The core differentiator: Socrata + ArcGIS cities all normalize into one
    canonical Permit schema. This is what makes Permy cross-city searchable."""
    from permy.adapters.austin import AustinAdapter
    from permy.adapters.chicago import ChicagoAdapter
    from permy.adapters.fortworth import FortWorthAdapter
    from permy.adapters.la import LAAdapter
    from permy.adapters.miami import MiamiAdapter
    from permy.adapters.nyc import NYCAdapter
    from permy.adapters.orlando import OrlandoAdapter
    from permy.adapters.seattle import SeattleAdapter
    from permy.adapters.sf import SFAdapter

    cases = [
        (AustinAdapter(), "austin", False),
        (NYCAdapter(), "nyc", False),
        (ChicagoAdapter(), "chicago", False),
        (SFAdapter(), "sf", False),
        (SeattleAdapter(), "seattle", False),
        (LAAdapter(), "la", True),
        (MiamiAdapter(), "miami", True),
        (OrlandoAdapter(), "orlando", False),
        (FortWorthAdapter(), "fortworth", True),
    ]
    for adapter, slug, arcgis in cases:
        rows = _load(slug, arcgis)
        if slug == "miami":
            adapter._geometry_wkid = 2236
        for raw in rows:
            p = adapter.normalize(raw)
            # every permit must have the canonical fields populated
            assert p.jurisdiction_slug, f"{slug}: missing jurisdiction_slug"
            assert p.canonical_uid, f"{slug}: missing canonical_uid"
            assert p.source_permit_id, f"{slug}: missing source_permit_id"
            assert p.address.full, f"{slug}: missing address.full"
            assert p.first_seen_at, f"{slug}: missing first_seen_at"
            assert p.enrichment is not None, f"{slug}: missing enrichment"
            # trade + work_class must be valid enum values
            assert p.trade_category in {"roofing", "solar", "hvac", "plumbing", "electrical",
                                        "building", "general", "demolition", "other", "unknown"}
            assert p.work_class in {"new_construction", "alteration", "addition", "remodel",
                                    "repair", "demolition", "other", "unknown"}
            # canonical_uid format is readable slug:source_id (not a hash)
            assert p.canonical_uid.startswith(p.jurisdiction_slug + ":")


def test_seven_cities_registered_in_adapters():
    # import all city modules so they register
    import permy.adapters.austin  # noqa: F401
    import permy.adapters.chicago  # noqa: F401
    import permy.adapters.fortworth  # noqa: F401
    import permy.adapters.la  # noqa: F401
    import permy.adapters.miami  # noqa: F401
    import permy.adapters.nyc  # noqa: F401
    import permy.adapters.orlando  # noqa: F401
    import permy.adapters.seattle  # noqa: F401
    import permy.adapters.sf  # noqa: F401
    from permy.adapters.base import ADAPTERS
    expected = {"austin-tx", "nyc-ny", "chicago-il", "sf-ca", "seattle-wa", "la-ca", "miami-fl", "orlando-fl", "fortworth-tx"}
    assert expected <= set(ADAPTERS.keys()), f"missing: {expected - set(ADAPTERS.keys())}"
