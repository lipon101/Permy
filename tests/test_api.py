from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from permy.api.main import app
from permy.db.repo import reset_repo

# dev-key-1 = free tier; dev-key-2 = pro tier (sees leads/intel/webhooks)
FREE = {"X-API-Key": "dev-key-1"}
PRO = {"X-API-Key": "dev-key-2"}
NONE = {}


@pytest.fixture(scope="module")
def client():
    reset_repo()  # force reseed from Austin fixture
    with TestClient(app) as c:
        yield c


# ---- auth ----
def test_missing_api_key_rejected(client):
    r = client.get("/v1/permits/search", headers=NONE)
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "missing_api_key"


def test_bearer_token_accepted(client):
    r = client.get("/v1/permits/search", headers={"Authorization": "Bearer dev-key-2"})
    assert r.status_code == 200


def test_health_is_public(client):
    r = client.get("/v1/health", headers=NONE)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---- permits ----
def test_permits_search_returns_normalized_records(client):
    r = client.get("/v1/permits/search?limit=5", headers=PRO)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert isinstance(body["permits"], list)
    p = body["permits"][0]
    # canonical schema stability: these keys ALWAYS present
    for k in ("id", "canonical_uid", "jurisdiction_slug", "address", "enrichment",
              "valuation_usd", "contractor", "owner", "trade_category", "dates"):
        assert k in p, f"{k} must always be present"
    # source provenance
    assert p["source_url"]
    assert p["source_name"]
    # confidence in 0..1
    assert 0.0 <= p["enrichment"]["confidence"] <= 1.0


def test_permits_search_filter_by_city(client):
    r = client.get("/v1/permits/search?city=Austin&limit=10", headers=PRO)
    assert r.status_code == 200
    for p in r.json()["permits"]:
        assert (p["address"]["city"] or "").lower() == "austin"


def test_permits_search_filter_by_trade(client):
    r = client.get("/v1/permits/search?trade=hvac&limit=10", headers=PRO)
    for p in r.json()["permits"]:
        assert p["trade_category"] == "hvac"


def test_permit_detail_by_id(client):
    search = client.get("/v1/permits/search?limit=1", headers=PRO).json()
    pid = search["permits"][0]["id"]
    r = client.get(f"/v1/permits/{pid}", headers=PRO)
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_permit_not_found(client):
    r = client.get("/v1/permits/does-not-exist-999", headers=PRO)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ---- properties ----
def test_property_resolve_and_timeline(client):
    # grab a real address from a permit
    p = client.get("/v1/permits/search?limit=1", headers=PRO).json()["permits"][0]
    addr = p["address"]["full"]
    r = client.get("/v1/properties/resolve", params={"address": addr}, headers=PRO)
    assert r.status_code == 200
    prop = r.json()
    assert prop["full_address"].lower() == addr.lower()
    # timeline
    tl = client.get(f"/v1/properties/{prop['id']}/timeline", headers=PRO)
    assert tl.status_code == 200
    body = tl.json()
    assert body["total_permits"] >= 1
    assert isinstance(body["permits"], list)


# ---- contractors ----
def test_contractors_search(client):
    r = client.get("/v1/contractors/search?limit=5", headers=PRO)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1


def test_contractor_activity(client):
    cs = client.get("/v1/contractors/search?limit=1", headers=PRO).json()
    cid = cs["contractors"][0]["id"]
    r = client.get(f"/v1/contractors/{cid}/activity", headers=PRO)
    assert r.status_code == 200
    act = r.json()
    assert act["permit_count"] >= 1
    assert 0.0 <= act["momentum"] <= 1.0
    assert act["value_band"] in ("<50k", "50k-500k", "500k+")


# ---- markets ----
def test_market_score(client):
    p = client.get("/v1/permits/search?limit=1", headers=PRO).json()["permits"][0]
    zipc = p["address"]["zip"]
    r = client.get(f"/v1/markets/{zipc}/development-score", headers=PRO)
    assert r.status_code == 200
    m = r.json()
    assert 0 <= m["hotspot_score"] <= 100
    assert m["narrative"]


# ---- leads (PRO gated) ----
def test_leads_ranked_pro(client):
    r = client.get("/v1/leads/ranked?persona=roofer&limit=3", headers=PRO)
    assert r.status_code == 200
    body = r.json()
    assert body["persona"] == "roofer"
    for lead in body["leads"]:
        assert 0 <= lead["lead_score"] <= 100
        assert lead["recommended_action"] in ("call_now", "qualify", "monitor", "skip")
        assert lead["reason"].startswith("[roofer]")


def test_leads_ranked_blocked_for_free(client):
    r = client.get("/v1/leads/ranked", headers=FREE)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "feature_not_available"


# ---- intelligence (PRO gated) ----
def test_intelligence_score_pro(client):
    p = client.get("/v1/permits/search?limit=1", headers=PRO).json()["permits"][0]
    r = client.post("/v1/intelligence/score", headers=PRO,
                    json={"permit_id": p["id"], "persona": "investor"})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["development_score"] <= 100
    assert isinstance(body["source_links"], list)


def test_intelligence_blocked_for_free(client):
    r = client.post("/v1/intelligence/score", headers=FREE,
                    json={"address": "10912 Mystic Timber Dr, Austin, TX 78754"})
    assert r.status_code == 403


# ---- RapidAPI subscription-header tier resolution (production-critical) ----
# RapidAPI's gateway forwards X-RapidAPI-Subscription = BASIC|PRO|ULTRA|MEGA|CUSTOM.
# A paid subscriber MUST get access to the tier they paid for; a free/basic
# subscriber MUST get a clean 403 with the upgrade message. This is what makes
# the product actually monetizable — do not let it regress.
def test_rapidapi_pro_subscriber_gets_contractors_not_leads(client):
    """A RapidAPI PRO subscriber ($49 → builder tier) gets contractors (export)
    but is blocked from leads (which needs ULTRA/pro tier)."""
    r = client.get("/v1/contractors/search?limit=3",
                   headers={"X-RapidAPI-Key": "buyer-pro", "X-RapidAPI-Subscription": "PRO"})
    assert r.status_code == 200
    r2 = client.get("/v1/leads/ranked?persona=roofer",
                    headers={"X-RapidAPI-Key": "buyer-pro", "X-RapidAPI-Subscription": "PRO"})
    assert r2.status_code == 403
    assert r2.json()["error"]["code"] == "feature_not_available"


def test_rapidapi_basic_subscriber_blocked_from_leads(client):
    """A RapidAPI BASIC (free) subscriber is blocked from leads with a clean 403."""
    r = client.get("/v1/leads/ranked?persona=roofer",
                   headers={"X-RapidAPI-Key": "buyer-basic", "X-RapidAPI-Subscription": "BASIC"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "feature_not_available"


def test_rapidapi_ultra_subscriber_gets_intelligence(client):
    """A RapidAPI ULTRA subscriber ($149 → pro tier) gets intel + leads access."""
    r = client.post("/v1/intelligence/score",
                    headers={"X-RapidAPI-Key": "buyer-ultra", "X-RapidAPI-Subscription": "ULTRA"},
                    json={"address": "10912 Mystic Timber Dr, Austin, TX 78754"})
    assert r.status_code == 200


def test_rapidapi_subscription_case_insensitive(client):
    """RapidAPI plan names are matched case-insensitively (ultra == ULTRA == Ultra)."""
    r = client.get("/v1/leads/ranked?persona=roofer&limit=1",
                   headers={"X-RapidAPI-Key": "buyer-x", "X-RapidAPI-Subscription": "ultra"})
    assert r.status_code == 200


def test_rapidapi_no_subscription_header_falls_back_to_free(client):
    """A RapidAPI caller with no subscription header still works at free tier."""
    r = client.get("/v1/permits/search?limit=1",
                   headers={"X-RapidAPI-Key": "buyer-new"})
    assert r.status_code == 200


def test_rapidapi_basic_still_searches(client):
    """A BASIC subscriber can still use the non-gated search endpoints."""
    r = client.get("/v1/permits/search?city=Austin&limit=1",
                   headers={"X-RapidAPI-Key": "buyer-basic", "X-RapidAPI-Subscription": "BASIC"})
    assert r.status_code == 200


# ---- alerts + webhooks (PRO gated) ----
def test_alert_crud_pro(client):
    r = client.post("/v1/alerts", headers=PRO, json={
        "persona": "roofer",
        "query": {"city": "Austin", "trade": "roofing"},
        "webhook_url": "https://example.com/hook",
    })
    assert r.status_code == 200
    aid = r.json()["id"]
    # list
    lst = client.get("/v1/alerts", headers=PRO)
    assert lst.status_code == 200
    assert any(a["id"] == aid for a in lst.json())
    # delete
    d = client.delete(f"/v1/alerts/{aid}", headers=PRO)
    assert d.status_code == 200
    assert d.json()["deleted"] is True


def test_alerts_blocked_for_free(client):
    r = client.post("/v1/alerts", headers=FREE, json={"query": {"city": "Austin"}})
    assert r.status_code == 403


def test_webhook_test_returns_envelope(client):
    # point at a non-existent host → delivered=False, but envelope shape must be valid
    r = client.post("/v1/webhooks/test", headers=PRO,
                    json={"url": "https://permy.invalid.hook/test"})
    assert r.status_code == 200
    body = r.json()
    assert "delivered" in body
    assert body["delivered"] is False


# ---- coverage + usage ----
def test_coverage(client):
    r = client.get("/v1/coverage", headers=PRO)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    city = body["cities"][0]
    assert city["city"] == "Austin"
    # honest coverage: Austin publishes phone (True) but not owner (False)
    assert city["fields"]["phone"] is True
    assert city["fields"]["owner"] is False


def test_usage(client):
    r = client.get("/v1/usage", headers=PRO)
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] in ("free", "builder", "pro", "business", "enterprise")
    assert "requests_today" in body


# ---- error envelope shape ----
def test_error_envelope_shape(client):
    r = client.get("/v1/permits/does-not-exist", headers=PRO)
    body = r.json()
    assert "error" in body
    assert body["error"]["code"]
    assert body["error"]["message"]
    assert body["error"]["docs_url"]
