from __future__ import annotations

import json
from pathlib import Path

import pytest

from permy.adapters.base import ADAPTERS
from permy.adapters.chicago import ChicagoAdapter, chicago
from permy.adapters.nyc import NYCAdapter, nyc

NYC_FIXTURE = Path(__file__).parent / "fixtures" / "nyc" / "sample_3.json"
CHI_FIXTURE = Path(__file__).parent / "fixtures" / "chicago" / "sample_3.json"


# ===========================================================================
# NYC DOB
# ===========================================================================
@pytest.fixture(scope="module")
def nyc_samples():
    return json.loads(NYC_FIXTURE.read_text())


@pytest.fixture
def nyc_adapter():
    return NYCAdapter()


def test_registry_has_nyc():
    assert "nyc-ny" in ADAPTERS


def test_nyc_source_meta_honest_coverage(nyc_adapter):
    meta = nyc_adapter.source_meta()
    assert meta["city"] == "New York"
    assert meta["source_portal"] == "socrata"
    cov = meta["coverage"]
    # NYC publishes geo + owner + phone (rich) — confirm honestly
    assert cov["geocode"] is True
    assert cov["owner"] is True
    assert cov["phone"] is True
    # NYC issuance dataset does NOT carry declared valuation — flag it honestly
    assert cov["valuation"] is False


def test_nyc_normalize_basic_fields(nyc_adapter, nyc_samples):
    p = nyc_adapter.normalize(nyc_samples[0])
    assert p.jurisdiction_slug == "nyc-ny"
    assert p.source_permit_id
    assert p.address.state == "NY"
    assert p.address.city  # borough
    assert p.source_url and p.source_url.startswith("https://")


def test_nyc_normalize_has_geo(nyc_adapter, nyc_samples):
    """NYC publishes GIS lat/lng — confirm the adapter preserves them."""
    found_geo = False
    for s in nyc_samples:
        p = nyc_adapter.normalize(s)
        if p.address.lat is not None and p.address.lng is not None:
            found_geo = True
            assert -75.0 < p.address.lng < -73.0  # NYC longitude range
            assert 40.0 < p.address.lat < 41.0     # NYC latitude range
            assert p.address.geocode_confidence is not None
    assert found_geo, "expected at least one NYC sample with geo coordinates"


def test_nyc_normalize_contractor_with_license(nyc_adapter, nyc_samples):
    """NYC publishes permittee license # + phone — richer than Austin."""
    found = False
    for s in nyc_samples:
        p = nyc_adapter.normalize(s)
        if p.contractor:
            found = True
            # NYC permittee carries phone
            if p.contractor.phone:
                digits = "".join(c for c in p.contractor.phone if c.isdigit())
                assert len(digits) >= 10
    assert found


def test_nyc_normalize_owner_published(nyc_adapter, nyc_samples):
    """NYC publishes owner name — rare among cities; confirm we capture it."""
    found_owner = False
    for s in nyc_samples:
        p = nyc_adapter.normalize(s)
        if p.owner and p.owner.name:
            found_owner = True
    assert found_owner, "expected NYC to publish owner name"


def test_nyc_normalize_trade_classification(nyc_adapter, nyc_samples):
    p = nyc_adapter.normalize(nyc_samples[0])
    assert p.trade_category in (
        "electrical", "hvac", "plumbing", "roofing", "solar",
        "building", "general", "demolition", "other", "unknown",
    )


def test_nyc_normalize_dates(nyc_adapter, nyc_samples):
    p = nyc_adapter.normalize(nyc_samples[0])
    # issuance_date present in fixture
    assert p.dates.issued is not None


def test_nyc_normalize_explicit_nulls(nyc_adapter, nyc_samples):
    p = nyc_adapter.normalize(nyc_samples[0])
    dumped = json.loads(p.model_dump_json())
    for k in ("valuation_usd", "housing_units", "new_add_sqft", "description", "parcel_id"):
        assert k in dumped, f"{k} must always be present (explicit null allowed)"


def test_nyc_normalize_parcel_bbl(nyc_adapter, nyc_samples):
    p = nyc_adapter.normalize(nyc_samples[0])
    # NYC uses BBL (borough-block-lot) or BIN as parcel identifier
    if p.parcel_id:
        assert isinstance(p.parcel_id, str)


@pytest.mark.live
def test_nyc_fetch_live_smoke():
    rows = nyc.fetch(limit=5)
    assert isinstance(rows, list)
    assert len(rows) <= 5


# ===========================================================================
# Chicago
# ===========================================================================
@pytest.fixture(scope="module")
def chi_samples():
    return json.loads(CHI_FIXTURE.read_text())


@pytest.fixture
def chi_adapter():
    return ChicagoAdapter()


def test_registry_has_chicago():
    assert "chicago-il" in ADAPTERS


def test_chi_source_meta_honest_coverage(chi_adapter):
    meta = chi_adapter.source_meta()
    assert meta["city"] == "Chicago"
    assert meta["source_portal"] == "socrata"
    cov = meta["coverage"]
    assert cov["geocode"] is True
    assert cov["valuation"] is False  # fees, not valuation — honest
    assert cov["phone"] is False       # contacts lack phone — honest


def test_chi_normalize_basic_fields(chi_adapter, chi_samples):
    p = chi_adapter.normalize(chi_samples[0])
    assert p.jurisdiction_slug == "chicago-il"
    assert p.source_permit_id
    assert p.address.state == "IL"
    assert p.address.city == "Chicago"
    assert p.source_url and p.source_url.startswith("https://")


def test_chi_normalize_has_geo(chi_adapter, chi_samples):
    found_geo = False
    for s in chi_samples:
        p = chi_adapter.normalize(s)
        if p.address.lat is not None and p.address.lng is not None:
            found_geo = True
            assert -88.0 < p.address.lng < -87.0  # Chicago longitude range
            assert 41.0 < p.address.lat < 42.5     # Chicago latitude range
    assert found_geo


def test_chi_normalize_address_assembled(chi_adapter, chi_samples):
    """Chicago address = street_number + direction + street_name."""
    p = chi_adapter.normalize(chi_samples[0])
    # address.full should contain the street name
    if p.address.street:
        assert "ST" in p.address.full.upper() or "AVE" in p.address.full.upper() or "DR" in p.address.full.upper()


def test_chi_normalize_contractor_from_contacts(chi_adapter, chi_samples):
    """Chicago lists contractors as contact_1..3; adapter picks the contractor-type one."""
    found = False
    for s in chi_samples:
        p = chi_adapter.normalize(s)
        if p.contractor and p.contractor.name:
            found = True
    assert found


def test_chi_normalize_work_description_preserved(chi_adapter, chi_samples):
    p = chi_adapter.normalize(chi_samples[0])
    assert p.description  # Chicago has rich work_description


def test_chi_normalize_fee_in_description_not_valuation(chi_adapter, chi_samples):
    """Chicago publishes fees, not valuation — fee must surface in description, valuation stays null."""
    p = chi_adapter.normalize(chi_samples[0])
    assert p.valuation_usd is None  # honest null
    # at least one sample should have a fee note appended to description
    has_fee_note = any("fees paid" in (chi_adapter.normalize(s).description or "")
                       for s in chi_samples)
    assert has_fee_note


def test_chi_normalize_trade_classification(chi_adapter, chi_samples):
    p = chi_adapter.normalize(chi_samples[0])
    assert p.trade_category in (
        "electrical", "hvac", "plumbing", "roofing", "solar",
        "building", "general", "demolition", "other", "unknown",
    )


def test_chi_normalize_dates(chi_adapter, chi_samples):
    p = chi_adapter.normalize(chi_samples[0])
    assert p.dates.issued is not None


def test_chi_normalize_explicit_nulls(chi_adapter, chi_samples):
    p = chi_adapter.normalize(chi_samples[0])
    dumped = json.loads(p.model_dump_json())
    for k in ("valuation_usd", "housing_units", "new_add_sqft", "owner", "parcel_id"):
        assert k in dumped


@pytest.mark.live
def test_chi_fetch_live_smoke():
    rows = chicago.fetch(limit=5)
    assert isinstance(rows, list)
    assert len(rows) <= 5


# ===========================================================================
# Cross-city: all three adapters normalize into the SAME schema
# ===========================================================================
def test_all_three_cities_produce_valid_permits():
    """The whole thesis: one Permit shape across Austin + NYC + Chicago."""
    from permy.adapters.austin import AustinAdapter
    austin_samples = json.loads((Path(__file__).parent / "fixtures" / "austin" / "sample_3.json").read_text())
    for adapter, samples in [
        (AustinAdapter(), austin_samples),
        (NYCAdapter(), nyc_samples_fixture()),
        (ChicagoAdapter(), chi_samples_fixture()),
    ]:
        for raw in samples:
            p = adapter.normalize(raw)
            # every permit must have these non-null fields
            assert p.jurisdiction_slug
            assert p.source_permit_id
            assert p.canonical_uid
            assert p.address.full
            assert p.source_name
            assert p.enrichment is not None
            # trade_category must be a valid enum value
            assert p.trade_category in (
                "roofing", "solar", "hvac", "plumbing", "electrical",
                "building", "general", "demolition", "other", "unknown",
            )
            # work_class must be a valid enum value
            assert p.work_class in (
                "new_construction", "alteration", "addition", "remodel",
                "repair", "demolition", "other", "unknown",
            )


def nyc_samples_fixture():
    return json.loads(NYC_FIXTURE.read_text())


def chi_samples_fixture():
    return json.loads(CHI_FIXTURE.read_text())
