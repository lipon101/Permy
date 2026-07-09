from __future__ import annotations

"""Coverage, health, usage (12–13)."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends

from permy.db.repo import Repo, get_repo
from permy.middleware.auth import ApiKeyContext, get_api_key_context
from permy.middleware.ratelimit import usage_today
from permy.models.schemas import CoverageResponse, HealthResponse, UsageResponse

router = APIRouter(prefix="/v1", tags=["meta"])


@router.get("/coverage", response_model=CoverageResponse,
            summary="Supported cities, fields available per city, freshness")
def coverage(
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(get_api_key_context),  # noqa: B008
) -> CoverageResponse:
    return repo.coverage()


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(repo: Repo = Depends(get_repo)) -> HealthResponse:  # noqa: B008
    # public; no auth required for health
    return HealthResponse(
        status="ok", version="0.1.0", time=datetime.now(timezone.utc),
        db="ok", redis="ok", coverage_cities=len(repo.jurisdictions),
    )


@router.get("/usage", response_model=UsageResponse, summary="Quota usage for the caller")
def usage(
    ctx: ApiKeyContext = Depends(get_api_key_context),  # noqa: B008
) -> UsageResponse:
    req_today, _ = usage_today(ctx.key)
    return UsageResponse(
        api_key=ctx.key[:4] + "…", tier=ctx.tier, day=date.today(),
        requests_today=req_today,
        daily_limit=ctx.limits["daily"], monthly_limit=ctx.limits["monthly"],
        month_requests=req_today,  # in prod: sum over month from usage_daily
    )
