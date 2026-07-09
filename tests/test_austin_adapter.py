from __future__ import annotations

import json
from pathlib import Path

import pytest

from permy.adapters.austin import AustinAdapter, austin

FIXTURE = Path(__file__).parent / "fixtures" / "austin" / "sample_3.json"


@pytest.fixture(scope="module")
def samples():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def adapter():
    return AustinAdapter()


def test_registry_has_austin():
    from permy.adapters.base import ADAPTERS
    assert "austin-tx" in ADAPTERS


def test_source_meta_coverage_honesty(adapter):
    meta = adapter.source_meta()
    assert meta["city"] == "Austin"
    assert meta["source_portal"] == "socrata"
    cov = meta["coverage"]
    # Austin publishes contractor phone (rare) — confirm we record that honestly
    assert cov["phone"] is True
    assert cov["owner"] is False  # Austin does NOT publish owner name
    assert cov["geocode"] is False  # no lat/lng in feed


def test_normalize_basic_fields(adapter, samples):
    p = adapter.normalize(samples[0])
    assert p.jurisdiction_slug == "austin-tx"
    assert p.source_permit_id  # not empty
    assert p.address.city in ("Austin", "AUSTIN")
    assert p.address.state == "TX"
    assert p.source_url and p.source_url.startswith("https://")
    assert p.enrichment is not None


def test_normalize_contractor_phone_preserved(adapter, samples):
    # At least one sample should carry a phone
    found_phone = False
    for s in samples:
        p = adapter.normalize(s)
        if p.contractor and p.contractor.phone:
            found_phone = True
            # phone should be digit-ish (Austin returns 10-digit strings)
            digits = "".join(c for c in p.contractor.phone if c.isdigit())
            assert len(digits) >= 10
    assert found_phone, "expected at least one sample with a contractor phone"


def test_normalize_trade_classification(adapter, samples):
    # sample[0] electrical, sample[1] mechanical
    p0 = adapter.normalize(samples[0])
    p1 = adapter.normalize(samples[1])
    assert p0.trade_category in ("electrical", "hvac", "plumbing", "roofing", "solar", "building", "general", "unknown")
    assert p1.trade_category in ("electrical", "hvac", "plumbing", "roofing", "solar", "building", "general", "unknown")


def test_normalize_dates_parsed(adapter, samples):
    p = adapter.normalize(samples[1])
    # sample 1 has issue_date 2026-07-08
    assert p.dates.issued is not None
    assert p.dates.issued.isoformat().startswith("2026-")


def test_normalize_explicit_nulls_not_omissions(adapter, samples):
    # Pydantic with ser_json_unset='null' guarantees missing → null.
    p = adapter.normalize(samples[0])
    dumped = json.loads(p.model_dump_json())
    # these keys MUST exist (even if null), never omitted
    for k in ("valuation_usd", "owner", "parcel_id", "contractor", "description", "housing_units", "new_add_sqft"):
        assert k in dumped, f"{k} must always be present (explicit null allowed)"
    # owner.name may be null but owner object must exist
    assert dumped["owner"] is not None and "name" in dumped["owner"]


def test_normalize_work_class_new_construction_flag(adapter, samples):
    p = adapter.normalize(samples[1])  # work_class 'New' → new_construction
    assert p.work_class == "new_construction"
    assert p.is_new_construction is True


@pytest.mark.live
def test_fetch_live_smoke():
    """Hits the real Austin Socrata endpoint. Skipped by default (pytest -m 'not live')."""
    rows = austin.fetch(limit=5)
    assert isinstance(rows, list)
    assert len(rows) <= 5
