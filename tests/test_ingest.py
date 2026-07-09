from __future__ import annotations

import json
from pathlib import Path

import pytest

from permy.adapters.austin import AustinAdapter
from permy.ingest.classify import classify_trade, classify_work_class
from permy.ingest.dedupe import (
    canonical_contractor_uid,
    canonical_permit_uid,
    canonical_property_uid,
)
from permy.ingest.pipeline import process_record, run_ingest
from permy.ingest.webhooks import build_event, deliver, sign_payload, verify_signature
from permy.models.schemas import Permit

FIXTURE = Path(__file__).parent / "fixtures" / "austin" / "sample_3.json"


@pytest.fixture
def samples():
    return json.loads(FIXTURE.read_text())


# ---- classify ----
def test_classify_trade_roofing():
    assert classify_trade("Tear off and replace roof shingles") == "roofing"


def test_classify_trade_solar():
    assert classify_trade("Install 8kW solar PV array") == "solar"


def test_classify_trade_unknown():
    assert classify_trade("Miscellaneous permit") == "unknown"


def test_classify_work_class():
    assert classify_work_class("New") == "new_construction"
    assert classify_work_class("Remodel") == "remodel"
    assert classify_work_class(None) == "unknown"


# ---- dedupe ----
def test_canonical_uids_stable():
    a = canonical_permit_uid("austin-tx", "123")
    b = canonical_permit_uid("austin-tx", "123")
    assert a == b and len(a) == 24


def test_canonical_uids_differ_by_city():
    a = canonical_permit_uid("austin-tx", "123")
    b = canonical_permit_uid("nyc-ny", "123")
    assert a != b


def test_property_uid_normalizes_whitespace_case():
    a = canonical_property_uid("101 Main St, Austin, TX")
    b = canonical_property_uid("  101 main st,  austin, tx ")
    assert a == b


def test_contractor_uid_includes_license():
    a = canonical_contractor_uid("austin-tx", "Acme Roofing", "LIC123")
    b = canonical_contractor_uid("austin-tx", "Acme Roofing", "LIC999")
    assert a != b


# ---- pipeline.process_record ----
def test_process_record_enriches_unknown_trade(samples):
    adapter = AustinAdapter()
    raw = samples[0]
    p = adapter.normalize(raw)
    # force unknown trade then re-classify via pipeline
    p.trade_category = "unknown"
    p2 = process_record(raw, adapter, geocoder=None)
    assert p2.canonical_uid  # set
    assert p2.enrichment.lead_score is not None
    assert 0 <= p2.enrichment.lead_score <= 100
    assert 0.0 <= p2.enrichment.confidence <= 1.0


def test_process_record_with_fake_geocoder(samples):
    adapter = AustinAdapter()
    def fake_geo(addr):
        return (30.2672, -97.7431, 0.9)
    p = process_record(samples[1], adapter, geocoder=fake_geo)
    assert p.address.lat == 30.2672
    assert p.address.lng == -97.7431
    assert p.address.geocode_confidence == 0.9


def test_process_record_geocoder_returns_none_is_safe(samples):
    adapter = AustinAdapter()
    p = process_record(samples[0], adapter, geocoder=lambda a: None)
    assert p.address.lat is None  # no crash, just stays un-geocoded


def test_process_record_dq_flags(samples):
    adapter = AustinAdapter()
    p = process_record(samples[0], adapter, geocoder=None)
    assert isinstance(p.enrichment.dq_flags, list)


def test_run_ingest_counts(samples):
    """run_ingest with a stubbed fetch + in-memory persister."""
    adapter = AustinAdapter()
    adapter.fetch = lambda since=None, limit=1000: samples  # type: ignore
    from permy.adapters.base import ADAPTERS
    ADAPTERS["austin-tx"] = adapter
    persisted = []
    counts = run_ingest("austin-tx", limit=10, geocoder=None, persister=persisted.append)
    assert counts["fetched"] == len(samples)
    assert counts["processed"] == len(samples)
    assert len(persisted) == len(samples)
    assert all(isinstance(x, Permit) for x in persisted)


# ---- webhooks ----
def test_webhook_signature_roundtrip():
    payload = b'{"event":"test"}'
    sig = sign_payload(payload, "secret123")
    assert verify_signature(payload, sig, "secret123") is True
    assert verify_signature(payload, "tampered", "secret123") is False
    assert verify_signature(payload, sig, "wrong-secret") is False


def test_build_event_envelope_shape():
    payload = build_event("permit.new", {"id": "123"}, "dev-key-1")
    env = json.loads(payload)
    assert env["event"] == "permit.new"
    assert env["data"]["id"] == "123"
    assert env["api_key"].endswith("…")  # masked


def test_deliver_to_invalid_host_returns_not_delivered():
    res = deliver("https://permy.invalid.example/hook", "permit.new",
                  {"id": "1"}, "dev-key-1", secret="s")
    assert res.delivered is False
    assert res.error  # some error string
