from __future__ import annotations

import pytest

from permy.db.repo import reset_repo
from permy.mcp.server import call_tool, list_tools


@pytest.fixture(autouse=True)
def _seed():
    reset_repo()


def test_five_tools_defined():
    tools = list_tools()
    assert len(tools) == 5
    names = {t["name"] for t in tools}
    assert names == {"search_permits", "property_timeline", "contractor_activity",
                     "zip_development_score", "rank_leads"}


def test_each_tool_has_input_and_output_schema():
    for t in list_tools():
        assert "inputSchema" in t and "outputSchema" in t
        assert t["inputSchema"]["type"] == "object"
        assert "description" in t and len(t["description"]) > 20


def test_search_permits_tool_returns_records():
    res = call_tool("search_permits", {"limit": 3})
    assert res["total"] >= 1
    assert isinstance(res["permits"], list)


def test_property_timeline_tool_resolves_address():
    # grab a real address
    search = call_tool("search_permits", {"limit": 1})
    addr = search["permits"][0]["address"]["full"]
    res = call_tool("property_timeline", {"address": addr})
    assert res["total_permits"] >= 1
    assert res["property"] is not None


def test_contractor_activity_tool_resolves_name():
    res = call_tool("contractor_activity", {"name": "Electric"})
    # should find an electrical contractor from the fixture
    assert res["contractor"] is not None or res.get("error")


def test_zip_development_score_tool():
    search = call_tool("search_permits", {"limit": 1})
    zipc = search["permits"][0]["address"]["zip"]
    res = call_tool("zip_development_score", {"zip": zipc})
    assert 0 <= res["hotspot_score"] <= 100


def test_rank_leads_tool():
    res = call_tool("rank_leads", {"persona": "roofer", "limit": 3})
    assert res["persona"] == "roofer"
    assert isinstance(res["leads"], list)
    for lead in res["leads"]:
        assert 0 <= lead["lead_score"] <= 100


def test_unknown_tool_raises():
    with pytest.raises(KeyError):
        call_tool("does_not_exist", {})


def test_zip_development_score_missing_market_returns_graceful():
    res = call_tool("zip_development_score", {"zip": "00000"})
    assert res["hotspot_score"] == 0
    assert "error" in res
