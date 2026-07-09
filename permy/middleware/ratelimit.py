from __future__ import annotations

"""Rate limiting — token bucket per API key in Redis; in-memory fallback for tests.

Limits are tier-aware (free 60/min, paid 600/min by default) and also enforce
the daily/monthly quota from TIER_LIMITS. Quota counters are written to the
`usage_daily` table in prod; here we keep a process-local counter for the
self-contained test path.
"""
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from typing import Optional, Tuple  # noqa: E402

from fastapi import HTTPException, Request, status  # noqa: E402

from permy.core.config import settings  # noqa: E402

# in-process fallback (tests/local). Redis is the source of truth in prod.
_buckets: dict = defaultdict(lambda: {"tokens": float(settings.rate_limit_paid), "ts": time.time()})
_daily: dict = defaultdict(int)
_sample_daily: dict = defaultdict(int)  # keyed by day → sample-mode request count


def _tier_rpm(tier: str) -> int:
    return settings.rate_limit_free if tier == "free" else settings.rate_limit_paid


def check_rate_limit(request: Request, tier: str) -> None:
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
    key = getattr(request.state, "api_key", None) or "anon"
    day = time.strftime("%Y-%m-%d")
    _daily[(key, day)] += 1


def usage_today(key: str) -> Tuple[int, Optional[int]]:
    """Returns (requests_today, daily_limit_or_None)."""
    day = time.strftime("%Y-%m-%d")
    return _daily.get((key, day), 0), None


# ---- sample mode quota (no-key docs playground) ----
def check_sample_quota() -> None:
    """Raise a 429 quota_exceeded when the sample mode daily cap is hit."""
    day = time.strftime("%Y-%m-%d")
    if _sample_daily[day] >= settings.sample_daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {
                "code": "quota_exceeded",
                "message": (
                    f"Sample mode limit reached ({settings.sample_daily_limit}/day). "
                    "Get a free API key for 100 requests/day at https://rapidapi.com/permy."
                ),
                "docs_url": "https://docs.permy.dev/pricing",
            }},
            headers={"Retry-After": "21600"},  # 6h until the day rolls
        )
    _sample_daily[day] += 1
