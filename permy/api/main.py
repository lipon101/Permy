from __future__ import annotations

"""Permy API — FastAPI app assembly.

OpenAPI 3.1 is generated from code at /openapi.json. The spec is the contract:
RapidAPI, the docs site, and the MCP server all derive from it.
"""
import time  # noqa: E402
import uuid  # noqa: E402
from collections import defaultdict  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from permy.api.v1.alerts import router as alerts_router  # noqa: E402
from permy.api.v1.contractors import router as contractors_router  # noqa: E402
from permy.api.v1.leads import router as leads_router  # noqa: E402
from permy.api.v1.meta import router as meta_router  # noqa: E402
from permy.api.v1.permits import router as permits_router  # noqa: E402
from permy.api.v1.sample import router as sample_router  # noqa: E402
from permy.core.config import settings  # noqa: E402
from permy.core.logging import logger  # noqa: E402
from permy.middleware.auth import get_api_key_context  # noqa: E402
from permy.middleware.ratelimit import check_rate_limit, record_usage  # noqa: E402
from permy.models.schemas import ErrorDetail, ErrorResponse  # noqa: E402

APP_VERSION = "0.1.0"

OPENAPI_TAGS = [
    {"name": "permits", "description": "Search and fetch normalized permits."},
    {"name": "contractors & markets", "description": "Contractor activity and ZIP-level development signals."},
    {"name": "leads & intelligence", "description": "Persona-ranked leads and full intelligence bundles (Pro+)."},
    {"name": "alerts & webhooks", "description": "Saved searches with signed HMAC webhook delivery (Pro+)."},
    {"name": "sample", "description": "No-key docs playground — capped, for trying the API before signup."},
    {"name": "meta", "description": "Coverage, health, usage."},
]


# Paths that are public (no API key, no rate-limit tier accounting). Sample
# endpoints are public but enforce their own daily quota in-route.
PUBLIC_PREFIXES = ("/v1/health", "/v1/sample", "/docs", "/openapi.json", "/redoc")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Security headers + request-id echo on EVERY response (public paths too).

    Running this as the outermost middleware means even /v1/health and /v1/sample
    get request-id echo + HSTS/nosniff/DENY headers.
    """

    async def dispatch(self, request: Request, call_next):
        # set request id early so it's available to handlers + the 404 envelope
        if not getattr(request.state, "request_id", None):
            request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Permy-Version"] = APP_VERSION
        response.headers["X-Request-Id"] = request.state.request_id
        # Hide framework fingerprint — don't advertise the server stack to
        # attackers mapping the attack surface. These overwrite uvicorn/starlette
        # defaults set later in the response chain.
        response.headers["Server"] = "permy"
        # Strip framework fingerprint header if present (MutableHeaders has no
        # .pop(); use guarded del).
        try:
            del response.headers["X-Powered-By"]
        except KeyError:
            pass
        return response


# Common vulnerability-scan paths (bots, crawlers, exploit kits). Reject fast
# with a plain 404 so they don't hit the error envelope or pollute logs.
_SCAN_PATHS = frozenset({
    "/.env", "/.git", "/.git/config", "/wp-admin", "/wp-login.php", "/xmlrpc.php",
    "/admin", "/admin/", "/phpinfo.php", "/.aws", "/.ssh", "/config.json",
    "/.DS_Store", "/vendor/phpunit", "/cgi-bin/", "/manager/html", "/solr",
    "/actuator", "/actuator/env", "/.well-known/security.txt",  # keep security.txt? no → 404
})


class PublicRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limit on the PUBLIC surface so it can't be abused, scraped,
    or used to DoS the host.

    Applies a per-IP token bucket to: /, /v1/health, /docs, /redoc, /openapi.json
    (the paths PUBLIC_PREFIXES covers, minus /v1/sample which has its own per-IP
    limiter in the sample router). Protected /v1/* paths are handled by
    RateLimitMiddleware (tier-aware); unknown routes fall through to the 404
    envelope. Also fast-rejects common scan paths with a bare 404 (no envelope,
    no log noise) so bots don't learn the API shape or burn cycles.
    """

    _PUBLIC_RATE_PATHS = frozenset({"/", "/v1/health", "/docs", "/redoc", "/openapi.json"})
    _BUCKETS: dict = defaultdict(lambda: {"tokens": 30.0, "ts": time.time()})
    # 30 req/min per IP on the public docs/spec surface — enough for a human
    # browsing /docs + Scalar fetching the spec, far below scrape/DoS rates.
    _CAPACITY = 30.0

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # fast-reject common scan/probe paths — bare 404, no body, no logging
        if path in _SCAN_PATHS or path.endswith(".php") or "/.git" in path:
            return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
        if path in self._PUBLIC_RATE_PATHS:
            ip = request.client.host if request.client and request.client.host else "unknown"
            now = time.time()
            b = self._BUCKETS[ip]
            elapsed = now - b["ts"]
            b["tokens"] = min(self._CAPACITY, b["tokens"] + elapsed * (self._CAPACITY / 60.0))
            b["ts"] = now
            if b["tokens"] < 1.0:
                return JSONResponse(
                    status_code=429,
                    content={"error": {
                        "code": "rate_limited",
                        "message": "Too many requests. Slow down.",
                    }},
                    headers={"Retry-After": "2"},
                )
            b["tokens"] -= 1.0
        return await call_next(request)


def _known_route(app: FastAPI, path: str) -> bool:
    """True when ``path`` matches a registered route (so auth applies; otherwise
    the 404 envelope should fire rather than a 401 auth leak on a bad path)."""
    for route in app.routes:
        if not hasattr(route, "path"):
            continue
        if route.path == path:
            return True
        # path-param routes: /permits/{permit_id} → compare by segment structure
        if "{" in route.path:
            segs = route.path.strip("/").split("/")
            test = path.strip("/").split("/")
            if len(segs) == len(test) and all(s == t or s.startswith("{") for s, t in zip(segs, test)):
                return True
    return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Auth + rate limit + usage accounting for protected /v1/* requests.

    Public paths (/v1/health, /v1/sample/*, docs) are skipped — sample mode
    enforces its own daily quota inside the sample router. Unknown routes are
    also skipped so the 404 envelope fires (no 401 auth leak on bad paths).

    ``self.app`` on BaseHTTPMiddleware points to the next middleware in the
    chain, not the FastAPI app — so we pass the real app in via ``kwarg`` and
    resolve routes against it.
    """

    def __init__(self, app, permy_app: FastAPI):
        super().__init__(app)
        self._permy_app = permy_app

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/v1/sample") or path in ("/v1/health", "/docs", "/openapi.json", "/redoc") \
                or not path.startswith("/v1"):
            return await call_next(request)
        # unknown route → let the 404 envelope fire (don't demand auth for a path
        # that doesn't exist; that would leak "valid route exists" via 401)
        if not _known_route(self._permy_app, path):
            return await call_next(request)
        try:
            ctx = get_api_key_context(request, request.headers.get("x-api-key"),
                                      request.headers.get("authorization"))
            check_rate_limit(request, ctx.tier)
        except Exception as exc:
            from fastapi import HTTPException as _HE
            if isinstance(exc, _HE):
                detail = exc.detail
                # attach request_id into the error envelope for support debugging
                if isinstance(detail, dict) and "error" in detail and "request_id" not in detail:
                    detail = {**detail, "request_id": request.state.request_id}
                return JSONResponse(status_code=exc.status_code, content=detail,
                                    headers=getattr(exc, "headers", None))
            raise
        start = time.time()
        response = await call_next(request)
        record_usage(request)
        dur = int((time.time() - start) * 1000)
        response.headers["X-Response-Time-ms"] = str(dur)
        logger.info("request", extra={
            "request_id": request.state.request_id, "method": request.method,
            "path": path, "status": response.status_code, "duration_ms": dur,
            "tier": getattr(ctx, "tier", None),
        })
        return response


def create_app() -> FastAPI:
    # In prod/staging, hide the interactive docs UI (Swagger /docs + ReDoc) so
    # the full API surface isn't browseable by attackers reverse-engineering it.
    # The raw /openapi.json stays available (rate-limited) so Scalar + RapidAPI
    # can still import the spec. Local/dev keeps docs on for convenience.
    _is_prod = settings.env in ("prod", "production", "staging")
    app = FastAPI(
        title="Permy — Building Permit & Construction Intelligence API",
        description=(
            "Building permit & construction intelligence: normalized permits, contractor activity, "
            "property timelines, and ZIP development signals — ranked, sourced, machine-readable."
        ),
        version=APP_VERSION,
        contact={"name": "Permy", "url": "https://permy.dev", "email": "hi@permy.dev"},
        license_info={"name": "Apache-2.0 (code); data per upstream license", "url": "https://docs.permy.dev/legal"},
        terms_of_service="https://docs.permy.dev/terms",
        servers=[
            {"url": "https://permy.p.rapidapi.com", "description": "RapidAPI production"},
            {"url": "https://api.permy.dev", "description": "Direct site"},
            {"url": "http://localhost:8000", "description": "Local dev"},
        ],
        openapi_tags=OPENAPI_TAGS,
        openapi_url="/openapi.json",
        docs_url=None if _is_prod else "/docs",
        redoc_url=None if _is_prod else "/redoc",
    )
    # CORS: open origins (public API, key-gated; the Vercel playground calls
    # cross-origin) but RESTRICT methods + headers to the explicit set we use,
    # removing the wildcard method/header surface that aids reconnaissance.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "X-API-Key", "Authorization", "Content-Type", "X-Request-Id",
            "X-RapidAPI-Key", "X-RapidAPI-Host", "X-RapidAPI-Subscription",
        ],
        allow_credentials=False,
    )
    # Order matters: the LAST add_middleware is the OUTERMOST. We want security
    # headers + request-id echo on EVERY response (including auth/rate-limit
    # errors), so SecurityHeadersMiddleware goes last. RateLimitMiddleware is
    # inner, so its auth-failure JSONResponse still gets the security headers.
    # We pass the real FastAPI app into RateLimitMiddleware so it can resolve
    # the route table (self.app on BaseHTTPMiddleware points to the next
    # middleware, not the app).
    app.add_middleware(RateLimitMiddleware, permy_app=app)
    app.add_middleware(SecurityHeadersMiddleware)
    # Outermost: reject scan paths + per-IP limit the public docs/spec surface
    # BEFORE auth/security headers (so a bot hammering /.env or scraping
    # /openapi.json never reaches the app or pollutes logs).
    app.add_middleware(PublicRateLimitMiddleware)

    app.include_router(permits_router)
    app.include_router(contractors_router)
    app.include_router(leads_router)
    app.include_router(alerts_router)
    app.include_router(sample_router)
    app.include_router(meta_router)

    # ---- unified error envelope ----
    from fastapi import HTTPException

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # If detail already follows our {error:...} envelope, pass it through.
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail,
                                headers=getattr(exc, "headers", None))
        # Otherwise wrap it.
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=ErrorDetail(code="http_error", message=str(exc.detail))
            ).model_dump(),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="validation_error",
                    message="Request validation failed.",
                    field=".".join(str(x.get("loc", ["?"])) for x in exc.errors()) or None,
                ),
                request_id=rid,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def fallback_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None)
        # don't leak internals; surface a stable code
        logger.error("unhandled error", extra={
            "request_id": rid, "method": request.method, "path": request.url.path,
            "error": f"{type(exc).__name__}: {exc}",
        })
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorDetail(code="internal_error", message="Unexpected error. Contact hi@permy.dev with request_id."),
                request_id=rid,
            ).model_dump(),
        )

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": "Permy", "version": APP_VERSION,
            "docs": "/docs", "openapi": "/openapi.json",
            "health": "/v1/health",
        }

    # ---- unknown route → 404 envelope (no 401 auth leak on bad paths) ----
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="not_found",
                    message=f"Unknown route: {request.method} {request.url.path}",
                    docs_url="https://docs.permy.dev",
                ),
                request_id=rid,
            ).model_dump(),
        )

    # ---- OpenAPI security scheme (for RapidAPI import + test console) ----
    # Declares the X-RapidAPI-Key header auth so that when the spec is imported
    # into RapidAPI (or viewed in /docs), the auth header is auto-populated for
    # buyers testing endpoints. RapidAPI adds its own gateway auth on top of this.
    from fastapi.openapi.utils import get_openapi

    def _permy_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title, version=app.version, description=app.description,
            routes=app.routes, openapi_version=app.openapi_version,
            servers=app.servers, tags=app.openapi_tags,
            contact=app.contact, license_info=app.license_info,
            terms_of_service=app.terms_of_service,
        )
        schema["components"] = schema.get("components", {})
        schema["components"]["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-RapidAPI-Key",
                "description": "Your RapidAPI app key (sent automatically by the gateway). "
                               "Direct-site callers may use X-API-Key or Authorization: Bearer instead.",
            }
        }
        # Apply only to protected /v1 routes — sample + health stay public.
        for path, methods in schema.get("paths", {}).items():
            if path.startswith("/v1/sample") or path in ("/v1/health",):
                continue
            for _method, op in methods.items():
                if isinstance(op, dict):
                    op["security"] = [{"ApiKeyAuth": []}]
        schema["info"]["x-logo"] = {"url": "https://permy.dev/assets/brand-mark.png"}
        app.openapi_schema = schema
        return schema

    app.openapi = _permy_openapi  # type: ignore[assignment]

    return app


app = create_app()


def run() -> None:
    import uvicorn
    uvicorn.run("permy.api.main:app", host=settings.host, port=settings.port, reload=(settings.env == "local"))
