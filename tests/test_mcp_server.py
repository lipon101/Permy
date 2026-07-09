from __future__ import annotations

"""Tests for the MCP server — tool dispatch + HTTP (JSON-RPC) transport.

The stdio transport needs the `mcp` package (not installed in CI); the HTTP
transport uses Starlette (bundled with FastAPI) and is fully testable here.
"""
import json  # noqa: E402

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from permy.db.repo import reset_repo  # noqa: E402
from permy.mcp.server import build_http_app, call_tool, list_tools  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    reset_repo()


# ---- tool registry ----
def test_list_tools_returns_five():
    tools = list_tools()
    assert len(tools) == 5
    names = {t["name"] for t in tools}
    assert names == {"search_permits", "property_timeline", "contractor_activity",
                     "zip_development_score", "rank_leads"}


def test_each_tool_has_input_schema():
    for t in list_tools():
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


# ---- in-process dispatch ----
def test_call_tool_search_permits():
    r = call_tool("search_permits", {"city": "Austin", "limit": 2})
    assert r["total"] >= 1
    assert len(r["permits"]) <= 2
    assert "canonical_uid" in r["permits"][0]


def test_call_tool_rank_leads():
    r = call_tool("rank_leads", {"persona": "roofer", "limit": 3})
    assert r["persona"] == "roofer"
    assert len(r["leads"]) <= 3
    assert 0 <= r["leads"][0]["lead_score"] <= 100


def test_call_tool_property_timeline_resolves_address():
    # grab a real address from the seeded data
    r = call_tool("search_permits", {"limit": 1})
    addr = r["permits"][0]["address"]["full"]
    tl = call_tool("property_timeline", {"address": addr})
    assert tl["total_permits"] >= 1
    assert tl["property"] is not None


def test_call_tool_property_timeline_unknown_address():
    tl = call_tool("property_timeline", {"address": "9999 Nowhere St, ZZ 99999"})
    assert tl["total_permits"] == 0


def test_call_tool_zip_development_score():
    # find a zip that exists in seeded data
    r = call_tool("search_permits", {"limit": 5})
    zips = {p["address"]["zip"] for p in r["permits"] if p["address"]["zip"]}
    assert zips, "seeded data should have zips"
    z = next(iter(zips))
    m = call_tool("zip_development_score", {"zip": z})
    assert m["zip"] == z
    assert 0 <= m["hotspot_score"] <= 100


def test_call_tool_zip_development_score_unknown():
    m = call_tool("zip_development_score", {"zip": "99999"})
    assert m["hotspot_score"] == 0


def test_call_tool_contractor_activity():
    # find a contractor that exists in seeded data (Austin/Miami have contractors)
    r = call_tool("search_permits", {"limit": 20})
    names = [p["contractor"]["name"] for p in r["permits"] if p.get("contractor") and p["contractor"].get("name")]
    if not names:
        pytest.skip("no contractors in seeded fixture set")
    act = call_tool("contractor_activity", {"name": names[0][:10]})  # substring
    assert act["permit_count"] >= 1


def test_call_tool_unknown_raises():
    with pytest.raises(KeyError):
        call_tool("does_not_exist", {})


# ---- HTTP transport (JSON-RPC) ----
@pytest.fixture
def client():
    return TestClient(build_http_app())


def test_http_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["tools"] == 5


def test_http_initialize(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["serverInfo"]["name"] == "permy-mcp"
    assert "tools" in result["capabilities"]


def test_http_tools_list(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["result"]["tools"]]
    assert len(names) == 5


def test_http_tools_call_search(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                  "params": {"name": "search_permits",
                                             "arguments": {"city": "Austin", "limit": 2}}})
    assert r.status_code == 200
    content = r.json()["result"]["content"][0]
    assert content["type"] == "text"
    data = json.loads(content["text"])
    assert data["total"] >= 1


def test_http_tools_call_rank_leads(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                  "params": {"name": "rank_leads",
                                             "arguments": {"persona": "solar", "limit": 2}}})
    assert r.status_code == 200
    data = json.loads(r.json()["result"]["content"][0]["text"])
    assert data["persona"] == "solar"


def test_http_unknown_tool_returns_error(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                  "params": {"name": "nope", "arguments": {}}})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32601


def test_http_unknown_method_returns_error(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 6, "method": "frobnicate"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32601


def test_http_parse_error(client):
    r = client.post("/mcp", data="not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
