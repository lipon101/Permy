from __future__ import annotations

"""Sample mode — no-key docs playground endpoints.

These mirror the real /v1 endpoints but:
  * require NO API key (so prospects can try them from the docs playground), and
  * cap responses at ``settings.sample_max_per_response`` records (default 10),
  * enforce a separate ``settings.sample_daily_limit`` (default 30/day) quota.

This is the single biggest RapidAPI conversion lever — let people feel the data
before they sign up. Every sample response carries ``X-Permy-Mode: sample`` so
clients can tell sample from real responses, and a ``sample: true`` field in the
body.

Auth bypass lives in the RateLimitMiddleware (it skips /v1/sample/*) and the
sample quota is enforced here via ``check_sample_quota()``.
"""
from typing import Optional  # noqa: E402

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status  # noqa: E402

from permy.core.config import settings  # noqa: E402
from permy.db.repo import Repo, get_repo  # noqa: E402
from permy.middleware.ratelimit import check_sample_quota  # noqa: E402
from permy.models.schemas import (  # noqa: E402
    ContractorsSearchResponse,
    CoverageResponse,
    Permit,
    PermitsSearchResponse,
    RankedLeadsResponse,
)

router = APIRouter(prefix="/v1/sample", tags=["sample"])

SAMPLE_MAX = settings.sample_max_per_response


def _enforce_sample_quota() -> None:
    """Bump the sample-day counter; raise 429 when the cap is hit."""
    check_sample_quota()


@router.get("/permits/search", response_model=PermitsSearchResponse,
            summary="[Sample, no key] Search permits — capped at 10 records")
def sample_search_permits(
    response: Response,
    city: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    zip: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    contractor: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    min_valuation: Optional[float] = Query(None, ge=0),
    max_valuation: Optional[float] = Query(None, ge=0),
    page: int = Query(1, ge=1),
    repo: Repo = Depends(get_repo),  # noqa: B008
) -> PermitsSearchResponse:
    _enforce_sample_quota()
    response.headers["X-Permy-Mode"] = "sample"
    params = {k: v for k, v in dict(
        city=city, state=state, zip=zip, trade=trade, status=status,
        contractor=contractor, keyword=keyword,
        min_valuation=min_valuation, max_valuation=max_valuation,
        sort="issued_date", sort_dir="desc", page=page, limit=SAMPLE_MAX,
    ).items() if v is not None}
    permits, total = repo.search_permits(params)
    # hard cap — never exceed sample max even if the repo ignored the limit
    permits = permits[:SAMPLE_MAX]
    return PermitsSearchResponse(page=page, limit=SAMPLE_MAX, total=total, permits=permits)


@router.get("/permits/{permit_id}", response_model=Permit,
            summary="[Sample, no key] Full permit detail")
def sample_get_permit(
    permit_id: str,
    response: Response,
    repo: Repo = Depends(get_repo),  # noqa: B008
) -> Permit:
    _enforce_sample_quota()
    response.headers["X-Permy-Mode"] = "sample"
    p = repo.get_permit(permit_id)
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": {"code": "not_found", "message": f"Permit '{permit_id}' not found.",
                      "docs_url": "https://docs.permy.dev/permits"}})
    return p


@router.get("/coverage", response_model=CoverageResponse,
            summary="[Sample, no key] Supported cities + per-city fields")
def sample_coverage(response: Response, repo: Repo = Depends(get_repo)) -> CoverageResponse:  # noqa: B008
    _enforce_sample_quota()
    response.headers["X-Permy-Mode"] = "sample"
    return repo.coverage()


@router.get("/contractors/search", response_model=ContractorsSearchResponse,
            summary="[Sample, no key] Search contractors — capped at 10 records")
def sample_search_contractors(
    response: Response,
    name: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    repo: Repo = Depends(get_repo),  # noqa: B008
) -> ContractorsSearchResponse:
    _enforce_sample_quota()
    response.headers["X-Permy-Mode"] = "sample"
    params = {k: v for k, v in dict(
        name=name, trade=trade, city=city, page=page, limit=SAMPLE_MAX,
    ).items() if v is not None}
    contractors, total = repo.search_contractors(params)
    contractors = contractors[:SAMPLE_MAX]
    return ContractorsSearchResponse(page=page, limit=SAMPLE_MAX, total=total, contractors=contractors)


@router.get("/leads/ranked", response_model=RankedLeadsResponse,
            summary="[Sample, no key] Ranked leads — capped at 10 records")
def sample_rank_leads(
    response: Response,
    persona: str = Query("roofer", pattern="^(roofer|solar|hvac|investor|supplier|insurer|general)$"),
    trade: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    repo: Repo = Depends(get_repo),  # noqa: B008
) -> RankedLeadsResponse:
    _enforce_sample_quota()
    response.headers["X-Permy-Mode"] = "sample"
    params = {k: v for k, v in dict(
        persona=persona, trade=trade, city=city, limit=SAMPLE_MAX,
    ).items() if v is not None}
    leads, total = repo.rank_leads(params)
    leads = leads[:SAMPLE_MAX]
    return RankedLeadsResponse(persona=persona, page=1, limit=SAMPLE_MAX, total=total, leads=leads)
