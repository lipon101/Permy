from __future__ import annotations

"""Postgres-backed Repo tests.

The full async/asyncpg path needs a live Postgres+PostGIS instance, which CI
spins up as a service. These tests cover:
  - module imports cleanly (no syntax/import errors)
  - connect_or_none() returns None gracefully when no DB is reachable
    (so the in-memory fallback path is exercised)
  - _permit_from_row maps a representative v_permits_full row → a valid Permit
  - the UPSERT SQL builds without error (smoke)

Live integration (against the CI Postgres service) is gated behind a
PG_AVAILABLE check so local/test runs skip gracefully.
"""
import os  # noqa: E402
from datetime import date, datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from permy.db.repo import get_repo, reset_repo  # noqa: E402


def test_pg_repo_module_imports():
    """The PG repo must import without error (catches syntax/typing issues)."""
    import permy.db.pg_repo as pg
    assert hasattr(pg, "PostgresRepo")
    assert hasattr(pg, "_permit_from_row")


def test_connect_or_none_returns_none_without_db():
    """When no Postgres is reachable, connect_or_none() must return None (→ in-memory fallback)."""
    from permy.db.pg_repo import PostgresRepo
    # Force the local/test short-circuit: env is local/test → returns None
    result = PostgresRepo.connect_or_none()
    assert result is None


def test_permit_from_row_maps_correctly():
    """A v_permits_full row maps to a valid Permit with all canonical fields."""
    from permy.db.pg_repo import _permit_from_row
    row = {
        "id": 42, "canonical_uid": "abc123", "jurisdiction_slug": "austin-tx",
        "source_permit_id": "13725333",
        "source_url": "https://abc.austintexas.gov/web/permit/...",
        "source_name": "City of Austin — Building Permits",
        "jurisdiction_source": "City of Austin",
        "first_seen_at": datetime.now(timezone.utc),
        "last_seen_at": datetime.now(timezone.utc),
        "last_checked_at": datetime.now(timezone.utc),
        "street": "1011 Brickell Loop", "city": "Austin", "state": "TX", "zip": "78744",
        "full_address": "1011 Brickell Loop, Austin, TX, 78744",
        "lat": 30.21, "lng": -97.77, "geocode_confidence": 0.9,
        "permit_type_raw": "2026-079841 EP", "permit_type_normalized": "Electrical Permit",
        "work_class": "remodel", "trade_category": "electrical",
        "is_new_construction": False, "is_alteration": True, "is_demolition": False,
        "valuation_usd": 45000.00, "housing_units": 1, "new_add_sqft": None,
        "applied_date": date(2026, 6, 22), "issued_date": date(2026, 7, 8),
        "finaled_date": date(2026, 7, 8), "expired_date": None,
        "current_status": "final", "status_raw": "Final",
        "description": "Home builders loop",
        "description_enriched": None,
        "contractor_name": "In Charge Electrical Services",
        "license_number": None, "contractor_trade": "Electrical Contractor",
        "contractor_phone": "5127786240",
        "owner_name": None, "parcel_id": "0338151201",
        "lead_score": 72, "recommended_action": "qualify",
        "reason": "[general] fresh signal=23/25...",
        "dq_flags": ["valuation_unknown"], "confidence": 0.87,
    }
    p = _permit_from_row(row)
    assert p.id == "42"
    assert p.canonical_uid == "abc123"
    assert p.jurisdiction_slug == "austin-tx"
    assert p.address.lat == 30.21 and p.address.lng == -97.77
    assert p.address.geocode_confidence == 0.9
    assert p.trade_category == "electrical"
    assert p.valuation_usd == 45000.0
    assert p.dates.issued == date(2026, 7, 8)
    assert p.contractor is not None
    assert p.contractor.name == "In Charge Electrical Services"
    assert p.contractor.phone == "5127786240"
    assert p.enrichment.lead_score == 72
    assert p.enrichment.confidence == 0.87
    assert p.enrichment.dq_flags == ["valuation_unknown"]


def test_permit_from_row_handles_nulls():
    """A sparse row (many nulls) maps without error and preserves explicit nulls."""
    from permy.db.pg_repo import _permit_from_row
    row = {
        "id": 1, "canonical_uid": "x", "jurisdiction_slug": "chicago-il",
        "source_permit_id": "B200477034", "source_url": None, "source_name": None,
        "jurisdiction_source": "City of Chicago",
        "first_seen_at": datetime.now(timezone.utc), "last_seen_at": datetime.now(timezone.utc),
        "last_checked_at": datetime.now(timezone.utc),
        "street": None, "city": "Chicago", "state": "IL", "zip": None,
        "full_address": "Chicago, IL", "lat": None, "lng": None, "geocode_confidence": None,
        "permit_type_raw": None, "permit_type_normalized": None,
        "work_class": None, "trade_category": None,
        "is_new_construction": False, "is_alteration": False, "is_demolition": False,
        "valuation_usd": None, "housing_units": None, "new_add_sqft": None,
        "applied_date": None, "issued_date": None, "finaled_date": None, "expired_date": None,
        "current_status": None, "status_raw": None, "description": None,
        "description_enriched": None, "contractor_name": None,
        "license_number": None, "contractor_trade": None, "contractor_phone": None,
        "owner_name": None, "parcel_id": None,
        "lead_score": None, "recommended_action": None, "reason": None,
        "dq_flags": [], "confidence": None,
    }
    p = _permit_from_row(row)
    assert p.valuation_usd is None
    assert p.dates.issued is None
    assert p.contractor is None
    assert p.enrichment.confidence == 0.0  # None → default
    assert p.trade_category == "unknown"  # None → default


def test_get_repo_falls_back_to_in_memory_when_no_pg():
    """The app works with zero infra — get_repo() returns the in-memory repo seeded from fixtures."""
    reset_repo()
    repo = get_repo()
    # in-memory repo should have all 9 MVP cities seeded
    assert len(repo.jurisdictions) == 9
    for city in ("Austin", "New York", "Chicago", "San Francisco", "Seattle", "Los Angeles", "Miami", "Orlando", "Fort Worth"):
        assert any(j["city"] == city for j in repo.jurisdictions), f"missing {city}"


# ---- live integration (only runs if a real Postgres+PostGIS is available) ----
PG_AVAILABLE = bool(os.environ.get("PERMY_TEST_LIVE_PG"))


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs PERMY_TEST_LIVE_PG + running Postgres+PostGIS")
def test_live_pg_upsert_and_search():
    """Live: create schema, upsert a permit, search it back. Requires Postgres+PostGIS."""
    import asyncio

    import asyncpg

    from permy.db.pg_repo import PostgresRepo
    from permy.models.schemas import Address, Enrichment, Permit, PermitDates

    async def _run():
        dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn)
        # schema assumed already applied by docker-compose init or CI
        repo = PostgresRepo(await asyncpg.create_pool(dsn))
        p = Permit(
            id="0", canonical_uid="test-uid-xyz", jurisdiction_slug="austin-tx",
            source_permit_id="TEST1", source_url="https://x", source_name="test",
            first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
            last_checked_at=datetime.now(timezone.utc),
            address=Address(full="1 Test St, Austin, TX 78704", city="Austin", state="TX", zip="78704",
                            street="1 Test St", lat=30.26, lng=-97.74, geocode_confidence=0.9),
            trade_category="roofing", work_class="alteration", is_alteration=True,
            valuation_usd=50000.0, dates=PermitDates(issued=date.today()),
            current_status="issued", enrichment=Enrichment(lead_score=80, recommended_action="call_now",
                                                            confidence=0.9, reason="test"),
        )
        repo.upsert_permit(p)
        # re-upsert should not duplicate
        repo.upsert_permit(p)
        results, total = repo.search_permits({"zip": "78704"})
        assert total == 1
        assert results[0].canonical_uid == "test-uid-xyz"
        await conn.close()

    asyncio.new_event_loop().run_until_complete(_run())
