from __future__ import annotations

"""Rate limiting — token bucket per API key in Redis; in-memory fallback for tests.

Enforces THREE layers so free users cannot abuse the API or the Render host:
  1. Per-minute token bucket (free 60/min, paid 600/min) — burst control.
  2. Daily quota (free 100/day) and monthly quota (paid monthly caps) — the
     tier caps from TIER_LIMITS. Previously only the token bucket ran; the
     daily/monthly caps were never checked, so a free user could pull 86K/day.
  3. Sample-mode quota is per-IP (not global) so one abuser can't burn the
     whole day's playground budget, and a per-IP floor rate limits hammering.

Quota counters are written to the `usage_daily` table in prod; here we keep a
process-local counter for the self-contained test path.
"""
import calendar  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from typing import Optional, Tuple  # noqa: E402

from fastapi import HTTPException, Request, status  # noqa: E402

from permy.core.config import TIER_LIMITS, settings  # noqa: E402

# in-process fallback (tests/local). Redis is the source of truth in prod.
# Sample burst capacity = the daily cap, so legitimate sequential use (incl.
# tests exhausting the daily quota) is never tripped by the burst limiter;
# only sustained rates above (cap)/min get throttled. Defined early so the
# _sample_rpm defaultdict can use it as its initial token count.
_SAMPLE_BURST = max(10, settings.sample_daily_limit)
_buckets: dict = defaultdict(lambda: {"tokens": float(settings.rate_limit_paid), "ts": time.time()})
_daily: dict = defaultdict(int)          # (key, day)   -> count
_monthly: dict = defaultdict(int)        # (key, month) -> count
_sample_daily: dict = defaultdict(int)   # (ip, day)    -> sample request count
_sample_rpm: dict = defaultdict(lambda: {"tokens": float(_SAMPLE_BURST), "ts": time.time()})  # per-IP sample burst


def _tier_rpm(tier: str) -> int:
    return settings.rate_limit_free if tier == "free" else settings.rate_limit_paid


def _quota_for(tier: str) -> Tuple[Optional[int], Optional[int]]:
    """Return (daily_limit, monthly_limit) for a tier, or (None, None) if uncapped."""
    lim = TIER_LIMITS.get(tier) or TIER_LIMITS["free"]
    return lim["daily"], lim["monthly"]


def _client_ip(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else "unknown"


def _check_quota(request: Request, tier: str) -> None:
    """Enforce daily + monthly caps. Raises 429 quota_exceeded when a cap is hit."""
    key = getattr(request.state, "api_key", None) or "anon"
    daily_limit, monthly_limit = _quota_for(tier)
    day = time.strftime("%Y-%m-%d")
    month = time.strftime("%Y-%m")
    if daily_limit is not None and _daily[(key, day)] >= daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {
                "code": "quota_exceeded",
                "message": (
                    f"Daily limit reached ({daily_limit}/day for {tier} tier). "
                    "Upgrade at https://rapidapi.com/permy."
                ),
                "docs_url": "https://docs.permy.dev/rate-limits",
            }},
            headers={"Retry-After": str(_seconds_until_midnight())},
        )
    if monthly_limit is not None and _monthly[(key, month)] >= monthly_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {
                "code": "quota_exceeded",
                "message": (
                    f"Monthly limit reached ({monthly_limit:,}/mo for {tier} tier). "
                    "Upgrade at https://rapidapi.com/permy."
                ),
                "docs_url": "https://docs.permy.dev/rate-limits",
            }},
            headers={"Retry-After": str(_seconds_until_month_end())},
        )


def _seconds_until_midnight() -> int:
    """Rough seconds until next UTC midnight (Retry-After hint)."""
    now = time.time()
    t = time.gmtime(now)
    midnight = calendar.timegm((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0))
    return max(60, midnight - int(now))


def _seconds_until_month_end() -> int:
    """Rough seconds until next month (Retry-After hint)."""
    now = time.time()
    t = time.gmtime(now)
    next_month = (t.tm_mon % 12) + 1
    next_year = t.tm_year + (1 if t.tm_mon == 12 else 0)
    month_end = calendar.timegm((next_year, next_month, 1, 0, 0, 0, 0, 0))
    return max(60, month_end - int(now))


def check_rate_limit(request: Request, tier: str) -> None:
    """Token bucket (per-minute) + daily/monthly quota enforcement."""
    _check_quota(request, tier)  # check caps BEFORE spending a token
    key = getattr(request.state, "api_key", None) or "anon"
    now = time.time()
    bucket = _buckets[key]
    rpm = _tier_rpm(tier)
    # refill
    elapsed = now - bucket["ts"]
    bucket["tokens"] = min(float(rpm), bucket["tokens"] + elapsed * (rpm / 60.0))
    bucket["ts"] = now
    if bucket["tokens"] < 1.0:
        retry = int(60 / rpm) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {
                "code": "rate_limited",
                "message": f"Rate limit exceeded ({rpm}/min for {tier} tier).",
                "docs_url": "https://docs.permy.dev/rate-limits",
            }},
            headers={"Retry-After": str(retry)},
        )
    bucket["tokens"] -= 1.0


def record_usage(request: Request) -> None:
    """Bump daily + monthly counters. Call AFTER a successful, authorized request."""
    key = getattr(request.state, "api_key", None) or "anon"
    day = time.strftime("%Y-%m-%d")
    month = time.strftime("%Y-%m")
    _daily[(key, day)] += 1
    _monthly[(key, month)] += 1


def usage_today(key: str, tier: str = "free") -> Tuple[int, Optional[int]]:
    """Returns (requests_today, daily_limit_or_None)."""
    day = time.strftime("%Y-%m-%d")
    daily_limit, _ = _quota_for(tier)
    return _daily.get((key, day), 0), daily_limit


# ---- sample mode quota (no-key docs playground) ----
# Per-IP so one abuser can't exhaust the global budget or hammer the host.
# _SAMPLE_BURST is defined near the top (used by the _sample_rpm defaultdict).
def check_sample_quota(request: Request) -> None:
    """Raise a 429 quota_exceeded when the per-IP sample mode cap is hit.

    Also enforces a per-IP burst limit so a single client can't rapid-fire the
    keyless endpoints and starve the Render host for real (paying) users.
    """
    ip = _client_ip(request)
    now = time.time()
    # per-IP burst bucket — protects the host from keyless hammering
    rb = _sample_rpm[ip]
    elapsed = now - rb["ts"]
    rb["tokens"] = min(float(_SAMPLE_BURST), rb["tokens"] + elapsed * (_SAMPLE_BURST / 60.0))
    rb["ts"] = now
    if rb["tokens"] < 1.0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {
                "code": "rate_limited",
                "message": "Too many sample requests. Slow down or get a free key at https://rapidapi.com/permy.",
                "docs_url": "https://docs.permy.dev/rate-limits",
            }},
            headers={"Retry-After": "6"},
        )
    rb["tokens"] -= 1.0
    # per-IP daily cap
    day = time.strftime("%Y-%m-%d")
    if _sample_daily[(ip, day)] >= settings.sample_daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {
                "code": "quota_exceeded",
                "message": (
                    f"Sample mode limit reached ({settings.sample_daily_limit}/day per IP). "
                    "Get a free API key for 100 requests/day at https://rapidapi.com/permy."
                ),
                "docs_url": "https://docs.permy.dev/pricing",
            }},
            headers={"Retry-After": str(_seconds_until_midnight())},
        )
    _sample_daily[(ip, day)] += 1
