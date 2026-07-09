from __future__ import annotations

"""Tests for the ops scripts (seed + ingest CLI) + alert matcher + webhooks.

Note: get_repo() auto-seeds all 7 cities from fixtures on first access, so the
in-memory repo is never empty. These tests assert the scripts add the expected
records and are idempotent, not that the repo starts empty.
"""
import json  # noqa: E402
import sys  # noqa: E402
from datetime import date, datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from permy.db.repo import get_repo, reset_repo  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    reset_repo()


# ---- seed script ----
def test_seed_all_cities_loads_seven():
    from permy.scripts.seed import run
    sys.argv = ["seed"]
    run()
    repo = get_repo()
    cities = {j["city"] for j in repo.jurisdictions}
    assert {"Austin", "New York", "Chicago", "San Francisco", "Seattle", "Los Angeles", "Miami"} <= cities
    by_slug = {}
    for p in repo.permits:
        by_slug[p.jurisdiction_slug] = by_slug.get(p.jurisdiction_slug, 0) + 1
    for slug in ("austin-tx", "nyc-ny", "chicago-il", "sf-ca", "seattle-wa", "la-ca", "miami-fl"):
        assert by_slug.get(slug, 0) >= 3, f"{slug} should have 3 records, got {by_slug.get(slug)}"


def test_seed_single_city():
    from permy.scripts.seed import run
    sys.argv = ["seed", "austin"]
    run()
    repo = get_repo()
    austin = [p for p in repo.permits if p.jurisdiction_slug == "austin-tx"]
    assert len(austin) == 3


def test_seed_is_idempotent():
    from permy.scripts.seed import run
    sys.argv = ["seed", "austin"]
    run()
    repo = get_repo()
    first = len(repo.permits)
    run()  # re-seed
    assert len(repo.permits) == first    # no duplicates


def test_seed_unknown_city_handled():
    from permy.scripts.seed import run
    sys.argv = ["seed", "nonexistent-city"]
    # unknown city → exit 1 with a helpful message (no crash)
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 1


def test_seed_multiple_cities():
    from permy.scripts.seed import run
    sys.argv = ["seed", "sf", "miami"]
    run()
    repo = get_repo()
    slugs = {p.jurisdiction_slug for p in repo.permits}
    assert "sf-ca" in slugs and "miami-fl" in slugs


# ---- ingest CLI ----
def test_ingest_cli_persists_to_repo():
    from permy.adapters.base import ADAPTERS
    fx = Path(__file__).parent / "fixtures" / "austin" / "sample_3.json"
    ADAPTERS["austin-tx"].fetch = lambda since=None, limit=1000: json.loads(fx.read_text())
    from permy.ingest.cli import run
    sys.argv = ["ingest", "austin-tx"]
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 0
    repo = get_repo()
    austin = [p for p in repo.permits if p.jurisdiction_slug == "austin-tx"]
    assert len(austin) >= 3
    assert all(p.canonical_uid for p in austin)


def test_ingest_cli_unknown_city_counts_failure():
    from permy.ingest.cli import run
    sys.argv = ["ingest", "nonexistent-city"]
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 1     # all cities failed


def test_ingest_cli_since_flag_parsed():
    from permy.ingest.cli import _parse_args
    cities, since = _parse_args(["--since=2026-01-15", "austin-tx"])
    assert cities == ["austin-tx"]
    assert since == date(2026, 1, 15)


def test_ingest_cli_since_flag_with_multiple_cities():
    from permy.ingest.cli import _parse_args
    cities, since = _parse_args(["austin-tx", "--since=2026-06-01", "sf-ca"])
    assert cities == ["austin-tx", "sf-ca"]
    assert since == date(2026, 6, 1)


def test_ingest_cli_invalid_since_exits_2():
    from permy.ingest.cli import run
    sys.argv = ["ingest", "--since=not-a-date", "austin-tx"]
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 2


# ---- alert matcher ----
def test_permit_matches_empty_query():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import permit_matches_query
    repo = get_repo()
    p = repo.permits[0]
    assert permit_matches_query(p, {}) is True       # open search


def test_permit_matches_city():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import permit_matches_query
    repo = get_repo()
    p = repo.permits[0]
    assert permit_matches_query(p, {"city": p.address.city}) is True
    assert permit_matches_query(p, {"city": "Nonexistent"}) is False


def test_permit_matches_trade():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import permit_matches_query
    repo = get_repo()
    p = next(p for p in repo.permits if p.trade_category != "unknown")
    assert permit_matches_query(p, {"trade": p.trade_category}) is True
    assert permit_matches_query(p, {"trade": "demolition"}) is (p.trade_category == "demolition")


def test_permit_matches_multiple_clauses_and_semantics():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import permit_matches_query
    repo = get_repo()
    p = repo.permits[0]
    # both clauses must match (AND)
    assert permit_matches_query(p, {"city": p.address.city, "state": p.address.state}) is True
    assert permit_matches_query(p, {"city": p.address.city, "state": "ZZ"}) is False


def test_match_alerts_returns_matches_with_scores():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import match_alerts
    from permy.models.schemas import Alert
    repo = get_repo()
    p = repo.permits[0]
    alert = Alert(id="1", persona="roofer", query={"city": p.address.city},
                  webhook_url="https://example.com/hook", is_active=True,
                  created_at=datetime.now(timezone.utc))
    matches = match_alerts(p, [alert])
    assert len(matches) == 1
    m = matches[0]
    assert m.alert.id == "1"
    assert 0 <= m.lead_score <= 100
    assert m.recommended_action in ("call_now", "qualify", "monitor", "skip")
    assert m.reason


def test_match_alerts_skips_inactive():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import match_alerts
    from permy.models.schemas import Alert
    repo = get_repo()
    p = repo.permits[0]
    alert = Alert(id="1", persona="roofer", query={"city": p.address.city},
                  webhook_url="https://example.com/hook", is_active=False,
                  created_at=datetime.now(timezone.utc))
    assert match_alerts(p, [alert]) == []


def test_match_alerts_no_match_when_query_excludes():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import match_alerts
    from permy.models.schemas import Alert
    repo = get_repo()
    p = repo.permits[0]
    alert = Alert(id="1", persona="roofer", query={"city": "Nonexistent City"},
                  webhook_url="https://example.com/hook", is_active=True,
                  created_at=datetime.now(timezone.utc))
    assert match_alerts(p, [alert]) == []


def test_build_webhook_payload_shape():
    from permy.db.repo import get_repo
    from permy.ingest.alert_matcher import build_webhook_payload, match_alerts
    from permy.models.schemas import Alert
    repo = get_repo()
    p = repo.permits[0]
    alert = Alert(id="7", persona="investor", query={"city": p.address.city},
                  webhook_url="https://example.com/hook", is_active=True,
                  created_at=datetime.now(timezone.utc))
    m = match_alerts(p, [alert])[0]
    payload = build_webhook_payload(m)
    assert payload["alert_id"] == "7"
    assert payload["persona"] == "investor"
    assert "permit" in payload
    assert payload["permit"]["canonical_uid"] == p.canonical_uid
    assert "lead_score" in payload and "recommended_action" in payload


# ---- webhook delivery (worker.match_and_deliver) ----
def test_match_and_deliver_fires_webhooks():
    from permy.db.repo import get_repo
    from permy.ingest.webhooks import DeliveryResult
    from permy.ingest.worker import match_and_deliver
    from permy.models.schemas import Alert
    repo = get_repo()
    alert = Alert(id="1", persona="roofer", query={"city": repo.permits[0].address.city},
                  webhook_url="https://example.com/hook", is_active=True,
                  created_at=datetime.now(timezone.utc))
    calls = []

    def stub(url, event_type, data, api_key, secret=None):
        calls.append((url, event_type, data["lead_score"], data["permit"]["canonical_uid"]))
        return DeliveryResult(delivered=True, status_code=200, attempt=1, error=None)

    counts = match_and_deliver(repo.permits, [alert], "dev-key-2", deliverer=stub)
    assert counts["matches"] >= 1
    assert counts["deliveries"] == counts["matches"]
    assert counts["delivered"] == counts["matches"]
    assert counts["failed"] == 0
    assert len(calls) >= 1
    assert calls[0][0] == "https://example.com/hook"
    assert calls[0][1] == "permit.new"


def test_match_and_deliver_skips_alert_without_webhook_url():
    from permy.db.repo import get_repo
    from permy.ingest.webhooks import DeliveryResult
    from permy.ingest.worker import match_and_deliver
    from permy.models.schemas import Alert
    repo = get_repo()
    alert = Alert(id="1", persona="roofer", query={"city": repo.permits[0].address.city},
                  webhook_url=None, is_active=True, created_at=datetime.now(timezone.utc))
    counts = match_and_deliver(repo.permits, [alert], "dev-key-2",
                               deliverer=lambda *a, **k: DeliveryResult(True, 200, 1, None))
    assert counts["matches"] >= 1
    assert counts["deliveries"] == 0      # matched but no webhook to deliver to


def test_match_and_deliver_counts_failures():
    from permy.db.repo import get_repo
    from permy.ingest.webhooks import DeliveryResult
    from permy.ingest.worker import match_and_deliver
    from permy.models.schemas import Alert
    repo = get_repo()
    alert = Alert(id="1", persona="roofer", query={"city": repo.permits[0].address.city},
                  webhook_url="https://example.com/hook", is_active=True,
                  created_at=datetime.now(timezone.utc))
    counts = match_and_deliver(repo.permits, [alert], "dev-key-2",
                               deliverer=lambda *a, **k: DeliveryResult(False, None, 1, "conn refused"))
    assert counts["failed"] == counts["matches"]
    assert counts["delivered"] == 0


# ---- list_active_alerts on the repo ----
def test_repo_list_active_alerts():
    from permy.db.repo import get_repo
    from permy.models.schemas import Alert
    repo = get_repo()
    repo.alerts["1"] = Alert(id="1", persona="roofer", query={"city": "Austin"},
                             webhook_url="https://x", is_active=True,
                             created_at=datetime.now(timezone.utc))
    repo.alerts["2"] = Alert(id="2", persona="roofer", query={"city": "NYC"},
                             webhook_url="https://y", is_active=False,
                             created_at=datetime.now(timezone.utc))
    active = repo.list_active_alerts()
    assert len(active) == 1
    assert active[0].id == "1"


# ---- webhook signing ----
def test_webhook_signature_roundtrip():
    from permy.ingest.webhooks import sign_payload, verify_signature
    payload = b'{"event":"permit.new","data":{"id":"1"}}'
    secret = "test-secret"
    sig = sign_payload(payload, secret)
    assert verify_signature(payload, sig, secret) is True
    assert verify_payload_tamper(payload, sig, secret) is False
    assert verify_signature(payload, "wrong-sig", secret) is False


def verify_payload_tamper(payload, sig, secret):
    from permy.ingest.webhooks import verify_signature
    return verify_signature(b'{"event":"tampered"}', sig, secret)
