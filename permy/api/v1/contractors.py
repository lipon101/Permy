from __future__ import annotations

"""Contractor + market endpoints (5–7)."""
from typing import Optional  # noqa: E402

from fastapi import APIRouter, Depends, HTTPException, Query, status  # noqa: E402

from permy.db.repo import Repo, get_repo  # noqa: E402
from permy.middleware.auth import ApiKeyContext, get_api_key_context, require_feature  # noqa: E402
from permy.models.schemas import (  # noqa: E402
    ContractorActivity,
    ContractorsSearchResponse,
    MarketScore,
)

router = APIRouter(prefix="/v1", tags=["contractors & markets"])


@router.get("/contractors/search", response_model=ContractorsSearchResponse,
            summary="Find contractors by name, license, city, trade, activity")
def search_contractors(
    name: Optional[str] = Query(None),
    license: Optional[str] = Query(None, alias="license"),
    city: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(require_feature("export")),  # noqa: B008
) -> ContractorsSearchResponse:
    params = {k: v for k, v in dict(
        name=name, license=license, city=city, trade=trade, page=page, limit=limit,
    ).items() if v is not None}
    contractors, total = repo.search_contractors(params)
    return ContractorsSearchResponse(page=page, limit=limit, total=total, contractors=contractors)


@router.get("/contractors/{contractor_id}/activity", response_model=ContractorActivity,
            summary="Permit count, trade mix, active cities, value bands, momentum, source confidence")
def contractor_activity(
    contractor_id: str,
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(require_feature("export")),  # noqa: B008
) -> ContractorActivity:
    act = repo.contractor_activity_get(contractor_id)
    if not act:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": {"code": "contractor_not_found",
                      "message": f"Contractor '{contractor_id}' not found.",
                      "docs_url": "https://docs.permy.dev/contractors"}})
    return act


@router.get("/markets/{zip}/development-score", response_model=MarketScore,
            summary="ZIP-level development momentum: volume, value, trade mix, MoM delta, hotspot 0–100")
def market_score(
    zip: str,
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(get_api_key_context),  # noqa: B008
) -> MarketScore:
    m = repo.market_score(zip)
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": {"code": "market_not_found",
                      "message": f"No market data for ZIP '{zip}'.",
                      "docs_url": "https://docs.permy.dev/markets"}})
    return m
