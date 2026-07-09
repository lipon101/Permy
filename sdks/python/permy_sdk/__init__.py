"""Permy Python SDK — typed client for the Permy Building Permit API.

A thin, synchronous client over ``httpx`` that mirrors the /v1 endpoints.
Designed for RapidAPI users: point ``base_url`` at the RapidAPI gateway and set
your RapidAPI key as ``api_key`` (sent as ``X-API-Key``).

    from permy_sdk import Permy
    p = Permy(api_key="your-rapidapi-key", base_url="https://permy.p.rapidapi.com")
    permits = p.search_permits(city="Austin", trade="roofing", limit=25)
    cov = p.coverage()
    lead = p.get_permit("austin-tx:12345")

All methods return parsed JSON (dicts/lists). Errors raise ``PermyError`` with
the upstream ``code``, ``message``, and HTTP status so callers can branch on
``quota_exceeded`` / ``rate_limited`` / ``not_found`` etc.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx


class PermyError(Exception):
    """Raised for non-2xx responses. Carries the unified error envelope fields."""

    def __init__(self, code: str, message: str, status_code: int,
                 request_id: Optional[str] = None, raw: Optional[Dict[str, Any]] = None):
        super().__init__(f"[{status_code}] {code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id
        self.raw = raw


class Permy:
    """Synchronous Permy API client.

    Args:
        api_key:   Your RapidAPI key (sent as X-API-Key). Required for /v1/*;
                   sample endpoints (/v1/sample/*) need no key.
        base_url:  API base. Use ``https://permy.p.rapidapi.com`` via RapidAPI,
                   ``https://api.permy.dev`` direct, or ``http://localhost:8000``.
        timeout:   Per-request timeout in seconds.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://permy.p.rapidapi.com",
                 timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)

    # ---- low-level ----
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        r = self._client.get(path, params=params)
        if r.status_code >= 400:
            try:
                body = r.json()
                err = body.get("error", {})
            except Exception:  # noqa: BLE001
                raise PermyError("http_error", r.text, r.status_code)
            raise PermyError(
                code=err.get("code", "http_error"),
                message=err.get("message", "request failed"),
                status_code=r.status_code,
                request_id=body.get("request_id"),
                raw=body,
            )
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- permits ----
    def search_permits(self, **params) -> Dict[str, Any]:
        """GET /v1/permits/search — city, state, zip, trade, status, contractor,
        keyword, min_valuation, max_valuation, issued_after, issued_before,
        sort, sort_dir, page, limit."""
        return self._get("/v1/permits/search", params=params)

    def get_permit(self, permit_id: str) -> Dict[str, Any]:
        """GET /v1/permits/{permit_id} — full permit detail."""
        return self._get(f"/v1/permits/{permit_id}")

    # ---- properties ----
    def resolve_property(self, address: str) -> Dict[str, Any]:
        """GET /v1/properties/resolve?address=..."""
        return self._get("/v1/properties/resolve", params={"address": address})

    def property_timeline(self, property_id: str) -> Dict[str, Any]:
        """GET /v1/properties/{property_id}/timeline"""
        return self._get(f"/v1/properties/{property_id}/timeline")

    # ---- contractors ----
    def search_contractors(self, **params) -> Dict[str, Any]:
        """GET /v1/contractors/search — name, trade, license, city, page, limit."""
        return self._get("/v1/contractors/search", params=params)

    def contractor_activity(self, contractor_id: str) -> Dict[str, Any]:
        """GET /v1/contractors/{contractor_id}/activity"""
        return self._get(f"/v1/contractors/{contractor_id}/activity")

    # ---- markets ----
    def market_score(self, zip: str) -> Dict[str, Any]:
        """GET /v1/markets/{zip}/development-score"""
        return self._get(f"/v1/markets/{zip}/development-score")

    # ---- leads + intelligence ----
    def rank_leads(self, persona: str = "roofer", **params) -> Dict[str, Any]:
        """GET /v1/leads/ranked?persona=... (Pro+)."""
        params = {"persona": persona, **params}
        return self._get("/v1/leads/ranked", params=params)

    def score_intelligence(self, address: Optional[str] = None,
                           permit_id: Optional[str] = None,
                           persona: str = "general",
                           project_type: Optional[str] = None) -> Dict[str, Any]:
        """POST /v1/intelligence/score (Pro+)."""
        body: Dict[str, Any] = {"persona": persona}
        if address:
            body["address"] = address
        if permit_id:
            body["permit_id"] = permit_id
        if project_type:
            body["project_type"] = project_type
        r = self._client.post("/v1/intelligence/score", json=body)
        if r.status_code >= 400:
            err = r.json().get("error", {})
            raise PermyError(err.get("code", "http_error"), err.get("message", "failed"),
                             r.status_code, r.json().get("request_id"))
        return r.json()

    # ---- alerts + webhooks ----
    def create_alert(self, persona: str, query: Dict[str, Any],
                     webhook_url: Optional[str] = None) -> Dict[str, Any]:
        """POST /v1/alerts (Pro+)."""
        body = {"persona": persona, "query": query}
        if webhook_url:
            body["webhook_url"] = webhook_url
        r = self._client.post("/v1/alerts", json=body)
        if r.status_code >= 400:
            err = r.json().get("error", {})
            raise PermyError(err.get("code", "http_error"), err.get("message", "failed"),
                             r.status_code, r.json().get("request_id"))
        return r.json()

    def list_alerts(self) -> Dict[str, Any]:
        return self._get("/v1/alerts")

    def delete_alert(self, alert_id: str) -> Dict[str, Any]:
        r = self._client.delete(f"/v1/alerts/{alert_id}")
        if r.status_code >= 400:
            err = r.json().get("error", {})
            raise PermyError(err.get("code", "http_error"), err.get("message", "failed"),
                             r.status_code, r.json().get("request_id"))
        return r.json()

    def test_webhook(self, url: str, secret: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"url": url}
        if secret:
            body["secret"] = secret
        r = self._client.post("/v1/webhooks/test", json=body)
        if r.status_code >= 400:
            err = r.json().get("error", {})
            raise PermyError(err.get("code", "http_error"), err.get("message", "failed"),
                             r.status_code, r.json().get("request_id"))
        return r.json()

    # ---- meta ----
    def coverage(self) -> Dict[str, Any]:
        return self._get("/v1/coverage")

    def health(self) -> Dict[str, Any]:
        return self._get("/v1/health")

    def usage(self) -> Dict[str, Any]:
        return self._get("/v1/usage")

    # ---- sample mode (no key) ----
    def sample_search_permits(self, **params) -> Dict[str, Any]:
        return self._get("/v1/sample/permits/search", params=params)

    def sample_coverage(self) -> Dict[str, Any]:
        return self._get("/v1/sample/coverage")


__all__ = ["Permy", "PermyError"]
