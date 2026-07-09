from __future__ import annotations

"""Tests for Orlando + Fort Worth adapters (Phase 7+ live cities).

Both fixtures are REAL live data captured 2026-07-10 — Orlando permits issued
that same day, Fort Worth building permits filed that day. No mocks.
"""
import json  # noqa: E402
from pathlib import Path  # noqa: E402

FX = Path(__file__).parent / "fixtures"


def _load(slug, arcgis):
    d = json.loads((FX / slug / "sample_3.json").read_text())
    return d["features"] if arcgis else d


# ---- Orlando (Socrata) ----
def test_orlando_normalize_basic():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    p = OrlandoAdapter().normalize(rows[0])
    assert p.jurisdiction_slug == "orlando-fl"
    assert p.address.state == "FL"
    assert p.source_permit_id
    assert p.canonical_uid == f"orlando-fl:{p.source_permit_id}"


def test_orlando_contractor_name_present():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    p = OrlandoAdapter().normalize(rows[0])
    assert p.contractor is not None
    assert p.contractor.name
    assert p.contractor.license_state == "FL"


def test_orlando_owner_published():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    p = OrlandoAdapter().normalize(rows[0])
    # Orlando publishes parcel_owner_name / property_owner_name
    assert p.owner is not None
    # at least one fixture has an owner name
    assert any(OrlandoAdapter().normalize(r).owner.name for r in rows)


def test_orlando_valuation_estimated_cost():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    p = OrlandoAdapter().normalize(rows[0])
    assert p.valuation_usd is not None and p.valuation_usd > 0


def test_orlando_geocode_from_geojson_when_present():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    # fixture includes a building permit with geocoded_column populated
    geo_permits = [OrlandoAdapter().normalize(r) for r in rows if r.get("geocoded_column")]
    assert geo_permits, "fixture should have at least one geocoded record"
    p = geo_permits[0]
    assert p.address.lat is not None and p.address.lng is not None
    assert 28.0 < p.address.lat < 29.0      # Orlando latitude
    assert -82.0 < p.address.lng < -81.0


def test_orlando_trade_from_application_type():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    a = OrlandoAdapter()
    trades = {a.normalize(r).trade_category for r in rows}
    # fixture has Mechanical + Electrical (+ Building) → hvac + electrical
    assert "hvac" in trades or "electrical" in trades


def test_orlando_status_mapping():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    a = OrlandoAdapter()
    for r in rows:
        p = a.normalize(r)
        assert p.current_status in {"applied", "issued", "active", "final",
                                    "expired", "cancelled", "withdrawn", "unknown"}


def test_orlando_source_meta_honest_flags():
    from permy.adapters.orlando import OrlandoAdapter
    m = OrlandoAdapter().source_meta()
    assert m["coverage"]["valuation"] is True
    assert m["coverage"]["contractor"] is True
    assert m["coverage"]["owner"] is True       # Orlando publishes owner
    assert m["coverage"]["phone"] is False      # no phone
    assert m["coverage"]["geocode"] is True
    assert m["source_portal"] == "socrata"


def test_orlando_dates_parsed():
    from permy.adapters.orlando import OrlandoAdapter
    rows = _load("orlando", arcgis=False)
    p = OrlandoAdapter().normalize(rows[0])
    # fixture permits issued 2026-07-09 (capture day)
    assert p.dates.issued is not None
    assert p.dates.issued.year == 2026


# ---- Fort Worth (ArcGIS) ----
def test_fortworth_normalize_basic():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    p = FortWorthAdapter().normalize(rows[0])
    assert p.jurisdiction_slug == "fortworth-tx"
    assert p.address.state == "TX"
    assert p.source_permit_id
    assert p.canonical_uid == f"fortworth-tx:{p.source_permit_id}"


def test_fortworth_explicit_lat_lon():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    p = FortWorthAdapter().normalize(rows[0])
    # Fort Worth publishes Latitude/Longitude attribute fields
    assert p.address.lat is not None and p.address.lng is not None
    assert 32.0 < p.address.lat < 33.0      # Fort Worth latitude
    assert -98.0 < p.address.lng < -97.0


def test_fortworth_owner_published():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    p = FortWorthAdapter().normalize(rows[0])
    assert p.owner is not None
    assert p.owner.name   # Owner_Full_Name populated


def test_fortworth_jobvalue_valuation():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    p = FortWorthAdapter().normalize(rows[0])
    # fixture is building permits with JobValue populated
    assert p.valuation_usd is not None and p.valuation_usd > 0


def test_fortworth_epoch_ms_dates_parsed():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    p = FortWorthAdapter().normalize(rows[0])
    # File_Date is epoch-ms (filed 2026-07-09)
    assert p.dates.applied is not None
    assert p.dates.applied.year == 2026


def test_fortworth_address_and_zip():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    p = FortWorthAdapter().normalize(rows[0])
    assert p.address.street is not None
    assert p.address.zip is not None
    assert len(p.address.zip) == 5


def test_fortworth_no_contractor_honest():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    p = FortWorthAdapter().normalize(rows[0])
    assert p.contractor is None   # not on this layer
    assert FortWorthAdapter().source_meta()["coverage"]["contractor"] is False


def test_fortworth_source_portal_arcgis():
    from permy.adapters.fortworth import FortWorthAdapter
    m = FortWorthAdapter().source_meta()
    assert m["source_portal"] == "arcgis"
    assert m["coverage"]["owner"] is True
    assert m["coverage"]["geocode"] is True
    assert m["coverage"]["valuation"] is True


def test_fortworth_trade_from_permit_type():
    from permy.adapters.fortworth import FortWorthAdapter
    rows = _load("fortworth", arcgis=True)
    a = FortWorthAdapter()
    # fixture is residential building permits
    for r in rows:
        p = a.normalize(r)
        assert p.trade_category == "building"
        assert p.is_new_construction or p.work_class in ("addition", "alteration", "other")
