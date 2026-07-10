from __future__ import annotations

"""Tests for sample mode (no-key playground) + production hardening:
security headers, request-id echo, 404 envelope (no auth leak), quota enforcement.
"""
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from permy.api.main import app  # noqa: E402
from permy.db.repo import reset_repo  # noqa: E402


@pytest.fixture
def client():
    reset_repo()
    import permy.middleware.ratelimit as rl
    rl._sample_daily.clear()
    rl._sample_rpm.clear()  # per-IP burst bucket — reset between tests
    return TestClient(app, raise_server_exceptions=False)


# ---- sample mode: no key required, capped ----
def test_sample_permits_search_no_key(client):
    r = client.get("/v1/sample/permits/search?limit=20")
    assert r.status_code == 200
    assert r.headers.get("X-Permy-Mode") == "sample"
    body = r.json()
    assert len(body["permits"]) <= 10          # hard cap, even though limit=20
    assert body["limit"] == 10
    assert body["total"] >= 1


def test_sample_coverage_no_key(client):
    r = client.get("/v1/sample/coverage")
    assert r.status_code == 200
    assert r.headers.get("X-Permy-Mode") == "sample"
    assert r.json()["total"] == 9              # 9 cities


def test_sample_leads_no_key(client):
    r = client.get("/v1/sample/leads/ranked?persona=roofer&limit=20")
    assert r.status_code == 200
    assert len(r.json()["leads"]) <= 10


def test_sample_contractors_no_key(client):
    r = client.get("/v1/sample/contractors/search?limit=20")
    assert r.status_code == 200
    assert len(r.json()["contractors"]) <= 10


def test_sample_get_permit_no_key(client):
    # grab a real permit id from sample search, then fetch it via sample endpoint
    s = client.get("/v1/sample/permits/search?limit=1").json()
    pid = s["permits"][0]["canonical_uid"]
    r = client.get(f"/v1/sample/permits/{pid}")
    assert r.status_code == 200
    assert r.headers.get("X-Permy-Mode") == "sample"
    assert r.json()["canonical_uid"] == pid


def test_sample_get_permit_404(client):
    r = client.get("/v1/sample/permits/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ---- sample quota enforcement ----
def test_sample_quota_exceeded_returns_429(client):
    import permy.middleware.ratelimit as rl
    rl._sample_daily.clear()
    rl._sample_rpm.clear()
    # default cap is 30/day; exhaust it
    for _ in range(30):
        assert client.get("/v1/sample/permits/search").status_code == 200
    r = client.get("/v1/sample/permits/search")
    assert r.status_code == 429
    assert r.json()["error"]["code"] in ("quota_exceeded", "rate_limited")


# ---- security headers on every response ----
def test_security_headers_present_on_health(client):
    r = client.get("/v1/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert "geolocation" in r.headers.get("Permissions-Policy", "")
    assert "max-age" in r.headers.get("Strict-Transport-Security", "")


def test_security_headers_present_on_sample(client):
    r = client.get("/v1/sample/coverage")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_security_headers_present_on_401(client):
    r = client.get("/v1/permits/search")
    assert r.status_code == 401
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


# ---- request-id echo (even on public paths) ----
def test_request_id_echoed_on_health(client):
    r = client.get("/v1/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers.get("X-Request-Id") == "abc-123"


def test_request_id_auto_generated_when_absent(client):
    r = client.get("/v1/health")
    assert r.headers.get("X-Request-Id")  # some uuid hex


def test_request_id_in_error_envelope(client):
    r = client.get("/v1/permits/search")  # 401
    body = r.json()
    assert body.get("request_id")  # present in the error envelope


# ---- unknown route → 404 envelope, NOT 401 auth leak ----
def test_unknown_route_returns_404_not_401(client):
    r = client.get("/v1/totally/fake/path")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert "X-Request-Id" in r.headers


def test_unknown_route_has_security_headers(client):
    r = client.get("/v1/totally/fake")
    assert r.status_code == 404
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


# ---- real endpoints still require a key ----
def test_protected_endpoint_requires_key(client):
    r = client.get("/v1/permits/search")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_api_key"


def test_protected_endpoint_works_with_key(client):
    r = client.get("/v1/permits/search?limit=5", headers={"X-API-Key": "dev-key-2"})
    assert r.status_code == 200
    assert len(r.json()["permits"]) == 5
