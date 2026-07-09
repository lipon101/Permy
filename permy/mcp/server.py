from __future__ import annotations

"""Permy MCP server — 5 tools for Claude / Cursor / agents.

Exposes a tiny, high-leverage subset of the API so an agent can answer
"What's being built near X?" / "Score this address for a roofer." without
learning the full REST surface. This is a real distribution channel in 2026:
agents that can call Permy directly become compounding distribution.

Tools:
  1. search_permits          → /v1/permits/search
  2. property_timeline       → /v1/properties/{id}/timeline  (resolves address first)
  3. contractor_activity     → /v1/contractors/{id}/activity (resolves name first)
  4. zip_development_score   → /v1/markets/{zip}/development-score
  5. rank_leads              → /v1/leads/ranked

The server speaks MCP over stdio (FastMCP) and proxies to the REST API using
the caller's PERMY_API_KEY. Input/output JSON schemas below are the contract
that the MCP layer + the agent both rely on.
"""
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Tool schemas (the source of truth — also rendered into the MCP listing copy)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "search_permits",
        "description": "Search normalized building permits by city, state, ZIP, trade, "
                       "permit type, status, date range, valuation, contractor name, or keyword. "
                       "Returns clean cross-city records with source links and confidence scores.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name (e.g. 'Austin')"},
                "state": {"type": "string", "description": "2-letter state (e.g. 'TX')"},
                "zip": {"type": "string", "description": "5-digit ZIP"},
                "trade": {"type": "string", "enum": [
                    "roofing", "solar", "hvac", "plumbing", "electrical",
                    "building", "general", "demolition", "other", "unknown"]},
                "status": {"type": "string", "enum": [
                    "applied", "issued", "active", "final", "expired",
                    "cancelled", "withdrawn", "unknown"]},
                "contractor": {"type": "string", "description": "Contractor name (substring)"},
                "keyword": {"type": "string", "description": "Free-text over description"},
                "min_valuation": {"type": "number", "minimum": 0},
                "max_valuation": {"type": "number", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "permits": {"type": "array", "items": {"type": "object"}},
                "total": {"type": "integer"},
                "page": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["permits", "total"],
        },
    },
    {
        "name": "property_timeline",
        "description": "Get the full permit history for a property (every permit, sorted, "
                       "categorized). Pass a street address; the tool resolves it first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Full street address"},
            },
            "required": ["address"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "property": {"type": "object"},
                "permits": {"type": "array", "items": {"type": "object"}},
                "total_permits": {"type": "integer"},
                "last_activity": {"type": "string", "format": "date"},
            },
            "required": ["property", "permits", "total_permits"],
        },
    },
    {
        "name": "contractor_activity",
        "description": "Get a contractor's permit activity: count, trade mix, active cities, "
                       "value bands, and momentum. Pass a contractor name; the tool resolves it first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contractor company name (substring)"},
                "city": {"type": "string", "description": "City to scope the search"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "contractor": {"type": "object"},
                "permit_count": {"type": "integer"},
                "total_valuation_usd": {"type": "number"},
                "trade_mix": {"type": "object"},
                "active_cities": {"type": "array", "items": {"type": "string"}},
                "value_band": {"type": "string"},
                "momentum": {"type": "number"},
            },
            "required": ["contractor", "permit_count"],
        },
    },
    {
        "name": "zip_development_score",
        "description": "Get ZIP-level development momentum: permit volume, total value, trade mix, "
                       "month-over-month delta, top contractors, and a hotspot score 0–100.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "zip": {"type": "string", "pattern": "^[0-9]{5}$"},
            },
            "required": ["zip"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "zip": {"type": "string"},
                "hotspot_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "permit_count_30d": {"type": "integer"},
                "total_value_30d": {"type": "number"},
                "trade_mix": {"type": "object"},
                "narrative": {"type": "string"},
            },
            "required": ["zip", "hotspot_score"],
        },
    },
    {
        "name": "rank_leads",
        "description": "Rank permit opportunities for a buyer persona (roofer, solar, hvac, "
                       "investor, supplier, insurer). Each lead has a 0–100 lead_score, a "
                       "recommended_action (call_now/qualify/monitor/skip), and a human reason.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "persona": {"type": "string", "enum": [
                    "roofer", "solar", "hvac", "investor", "supplier", "insurer", "general"]},
                "city": {"type": "string"},
                "state": {"type": "string"},
                "zip": {"type": "string"},
                "trade": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "required": ["persona"],
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "persona": {"type": "string"},
                "leads": {"type": "array", "items": {"type": "object"}},
                "total": {"type": "integer"},
            },
            "required": ["persona", "leads"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch — calls the repo directly (in-process) so the MCP server and
# the REST API share one data layer. In a standalone deployment, swap these
# for httpx calls to the REST API with the caller's PERMY_API_KEY.
# ---------------------------------------------------------------------------
from permy.db.repo import get_repo


def _tool_search_permits(args: Dict[str, Any]) -> Dict[str, Any]:
    repo = get_repo()
    permits, total = repo.search_permits({k: v for k, v in args.items() if v is not None})
    return {"permits": [p.model_dump(mode="json") for p in permits], "total": total,
            "page": 1, "limit": args.get("limit", 25)}


def _tool_property_timeline(args: Dict[str, Any]) -> Dict[str, Any]:
    repo = get_repo()
    prop = repo.resolve_property(args["address"])
    if not prop:
        return {"property": None, "permits": [], "total_permits": 0, "error": "address not found"}
    tl = repo.property_timeline(prop.id)
    if not tl:
        return {"property": prop.model_dump(mode="json"), "permits": [], "total_permits": 0}
    return {
        "property": tl.property.model_dump(mode="json"),
        "permits": [e.model_dump(mode="json") for e in tl.permits],
        "total_permits": tl.total_permits,
        "last_activity": tl.last_activity.isoformat() if tl.last_activity else None,
    }


def _tool_contractor_activity(args: Dict[str, Any]) -> Dict[str, Any]:
    repo = get_repo()
    contractors, _ = repo.search_contractors({"name": args["name"], "city": args.get("city"), "limit": 1})
    if not contractors:
        return {"contractor": None, "permit_count": 0, "error": "contractor not found"}
    c = contractors[0]
    act = repo.contractor_activity_get(c.id)
    if not act:
        return {"contractor": c.model_dump(mode="json"), "permit_count": 0}
    return act.model_dump(mode="json")


def _tool_zip_development_score(args: Dict[str, Any]) -> Dict[str, Any]:
    repo = get_repo()
    m = repo.market_score(args["zip"])
    if not m:
        return {"zip": args["zip"], "hotspot_score": 0, "error": "no market data for zip"}
    return m.model_dump(mode="json")


def _tool_rank_leads(args: Dict[str, Any]) -> Dict[str, Any]:
    repo = get_repo()
    leads, total = repo.rank_leads({k: v for k, v in args.items() if v is not None})
    return {"persona": args["persona"], "total": total,
            "leads": [l.model_dump(mode="json") for l in leads]}


_DISPATCH = {
    "search_permits": _tool_search_permits,
    "property_timeline": _tool_property_timeline,
    "contractor_activity": _tool_contractor_activity,
    "zip_development_score": _tool_zip_development_score,
    "rank_leads": _tool_rank_leads,
}


# ---------------------------------------------------------------------------
# FastMCP server (optional — only if the `mcp` package is installed)
# ---------------------------------------------------------------------------
def build_server():  # pragma: no cover — requires mcp package
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise RuntimeError("Install the MCP SDK: pip install 'permy[mcp]'")

    mcp = FastMCP("permy")

    @mcp.tool()
    def search_permits(city: Optional[str] = None, state: Optional[str] = None,
                       zip: Optional[str] = None, trade: Optional[str] = None,
                       status: Optional[str] = None, contractor: Optional[str] = None,
                       keyword: Optional[str] = None, min_valuation: Optional[float] = None,
                       max_valuation: Optional[float] = None, limit: int = 25) -> str:
        """Search normalized building permits across supported cities."""
        import json
        return json.dumps(_tool_search_permits({k: v for k, v in dict(
            city=city, state=state, zip=zip, trade=trade, status=status,
            contractor=contractor, keyword=keyword, min_valuation=min_valuation,
            max_valuation=max_valuation, limit=limit).items() if v is not None}))

    @mcp.tool()
    def property_timeline(address: str) -> str:
        """Full permit history for a property (pass a street address)."""
        import json
        return json.dumps(_tool_property_timeline({"address": address}))

    @mcp.tool()
    def contractor_activity(name: str, city: Optional[str] = None) -> str:
        """A contractor's permit activity, trade mix, and momentum."""
        import json
        return json.dumps(_tool_contractor_activity({"name": name, "city": city}))

    @mcp.tool()
    def zip_development_score(zip: str) -> str:
        """ZIP-level development momentum + hotspot score 0–100."""
        import json
        return json.dumps(_tool_zip_development_score({"zip": zip}))

    @mcp.tool()
    def rank_leads(persona: str, city: Optional[str] = None, state: Optional[str] = None,
                   zip: Optional[str] = None, trade: Optional[str] = None, limit: int = 25) -> str:
        """Rank permit opportunities for a buyer persona."""
        import json
        return json.dumps(_tool_rank_leads({k: v for k, v in dict(
            persona=persona, city=city, state=state, zip=zip, trade=trade, limit=limit
        ).items() if v is not None}))

    return mcp


def run_stdio():  # pragma: no cover
    build_server().run()


# ---------------------------------------------------------------------------
# Remote-API mode — point the MCP tools at a deployed Permy REST API instead of
# the in-process repo. Used when the MCP server is hosted separately from the
# API (e.g. MCP on Fly, API on Render). Set PERMY_API_URL + PERMY_API_KEY.
# ---------------------------------------------------------------------------
import os as _os
import json as _json

_PERMY_API_URL = _os.environ.get("PERMY_API_URL", "").rstrip("/")
_PERMY_API_KEY = _os.environ.get("PERMY_API_KEY", "")


def _remote_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Call the deployed Permy REST API. Used when PERMY_API_URL is set."""
    import httpx
    headers = {"Accept": "application/json"}
    if _PERMY_API_KEY:
        headers["X-API-Key"] = _PERMY_API_KEY
    with httpx.Client(base_url=_PERMY_API_URL, timeout=30.0, headers=headers) as c:
        r = c.get(path, params=params)
        r.raise_for_status()
        return r.json()


def _remote_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    import httpx
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if _PERMY_API_KEY:
        headers["X-API-Key"] = _PERMY_API_KEY
    with httpx.Client(base_url=_PERMY_API_URL, timeout=30.0, headers=headers) as c:
        r = c.post(path, json=body)
        r.raise_for_status()
        return r.json()


def _is_remote() -> bool:
    return bool(_PERMY_API_URL)


# Tool dispatch that routes to remote API when configured, in-process repo otherwise.
def _tool_search_permits_remote(args: Dict[str, Any]) -> Dict[str, Any]:
    return _remote_get("/v1/permits/search", {k: v for k, v in args.items() if v is not None})


def _tool_property_timeline_remote(args: Dict[str, Any]) -> Dict[str, Any]:
    # resolve address first, then fetch timeline
    prop = _remote_get("/v1/properties/resolve", {"address": args["address"]})
    if not prop or prop.get("error"):
        return {"property": None, "permits": [], "total_permits": 0, "error": "address not found"}
    tl = _remote_get(f"/v1/properties/{prop['id']}/timeline")
    return tl


def _tool_contractor_activity_remote(args: Dict[str, Any]) -> Dict[str, Any]:
    cs = _remote_get("/v1/contractors/search", {"name": args["name"], "city": args.get("city"), "limit": 1})
    contractors = cs.get("contractors", [])
    if not contractors:
        return {"contractor": None, "permit_count": 0, "error": "contractor not found"}
    cid = contractors[0]["id"]
    return _remote_get(f"/v1/contractors/{cid}/activity")


def _tool_zip_development_score_remote(args: Dict[str, Any]) -> Dict[str, Any]:
    return _remote_get(f"/v1/markets/{args['zip']}/development-score")


def _tool_rank_leads_remote(args: Dict[str, Any]) -> Dict[str, Any]:
    return _remote_get("/v1/leads/ranked", {k: v for k, v in args.items() if v is not None})


_REMOTE_DISPATCH = {
    "search_permits": _tool_search_permits_remote,
    "property_timeline": _tool_property_timeline_remote,
    "contractor_activity": _tool_contractor_activity_remote,
    "zip_development_score": _tool_zip_development_score_remote,
    "rank_leads": _tool_rank_leads_remote,
}


def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke a tool by name. Routes to the remote API when PERMY_API_URL is set,
    otherwise the in-process repo. Raises KeyError if the tool is unknown."""
    if _is_remote():
        fn = _REMOTE_DISPATCH[name]
    else:
        fn = _DISPATCH[name]
    return fn(args)


def list_tools() -> List[Dict[str, Any]]:
    """Return the 5 tool definitions (for MCP list_tools / registry listings)."""
    return TOOL_DEFINITIONS


# ---------------------------------------------------------------------------
# HTTP transport — exposes the 5 tools as a JSON-RPC endpoint so the MCP server
# can be hosted remotely (Fly/Render) and called by Claude/Cursor over HTTP.
# Uses Starlette (bundled with FastAPI) so there's no extra dependency. The
# stdio transport (build_server().run()) is for local agent use; HTTP is for
# remote-hosted agents + the Smithery/Glama registries.
# ---------------------------------------------------------------------------
def build_http_app():
    """Return a Starlette app exposing /mcp (JSON-RPC: tools/list, tools/call)
    + /health. This is the transport for a remotely-hosted MCP server."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    import json

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({
            "name": "permy-mcp", "status": "ok",
            "tools": len(TOOL_DEFINITIONS),
            "mode": "remote" if _is_remote() else "in-process",
        })

    async def mcp(request: Request) -> JSONResponse:
        """Minimal MCP-over-HTTP JSON-RPC handler: tools/list + tools/call."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}}, status_code=400)
        method = body.get("method")
        rid = body.get("id")
        params = body.get("params", {}) or {}
        if method == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "permy-mcp", "version": "0.1.0"},
            }})
        if method == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOL_DEFINITIONS}})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            try:
                result = call_tool(name, args)
            except KeyError:
                return JSONResponse({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"unknown tool: {name}"}}, status_code=400)
            except Exception as e:  # noqa: BLE001
                return JSONResponse({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32603, "message": f"tool error: {e}"}}, status_code=500)
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}]}})
        return JSONResponse({"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"unknown method: {method}"}}, status_code=400)

    return Starlette(routes=[
        __import__("starlette.routing", fromlist=["Route"]).Route("/health", health, methods=["GET"]),
        __import__("starlette.routing", fromlist=["Route"]).Route("/mcp", mcp, methods=["POST", "GET"]),
    ])


def run_http(host: str = "0.0.0.0", port: int = 8765):  # pragma: no cover
    """Run the MCP server over HTTP (for remote hosting)."""
    import uvicorn
    uvicorn.run(build_http_app(), host=host, port=port, log_level="info")


def run(transport: str = "stdio"):  # pragma: no cover
    """Entry point for `permy-mcp`. transport='stdio' (local agents) or 'http'."""
    if transport == "http":
        run_http()
    else:
        run_stdio()
