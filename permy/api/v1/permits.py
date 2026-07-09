from __future__ import annotations

"""Permit + property endpoints (1–4)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from permy.db.repo import Repo, get_repo
from permy.middleware.auth import ApiKeyContext, get_api_key_context
from permy.models.schemas import Permit, PermitsSearchResponse, Property, PropertyTimeline

router = APIRouter(prefix="/v1", tags=["permits"])


@router.get("/permits/search", response_model=PermitsSearchResponse,
            summary="Search normalized permits")
def search_permits(
    city: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    zip: Optional[str] = Query(None),
    trade: Optional[str] = Query(None, description="roofing|solar|hvac|plumbing|electrical|building|general|demolition|other|unknown"),
    permit_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="applied|issued|active|final|expired|cancelled|withdrawn|unknown"),
    contractor: Optional[str] = Query(None, description="Contractor name (substring)"),
    keyword: Optional[str] = Query(None, description="Free-text over description"),
    min_valuation: Optional[float] = Query(None, ge=0),
    max_valuation: Optional[float] = Query(None, ge=0),
    issued_after: Optional[date] = Query(None),
    issued_before: Optional[date] = Query(None),
    bbox: Optional[str] = Query(None, description="west,south,east,north — geo bounding box"),
    sort: str = Query("issued_date", pattern="^(issued_date|valuation_usd|lead_score)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(get_api_key_context),  # noqa: B008
) -> PermitsSearchResponse:
    params = {k: v for k, v in dict(
        city=city, state=state, zip=zip, trade=trade, permit_type=permit_type,
        status=status, contractor=contractor, keyword=keyword,
        min_valuation=min_valuation, max_valuation=max_valuation,
        issued_after=issued_after, issued_before=issued_before,
        sort=sort, sort_dir=sort_dir, page=page, limit=limit,
    ).items() if v is not None}
    if bbox:
        # bbox parsing handled in PG impl; ignored in in-memory repo
        params["bbox"] = bbox
    permits, total = repo.search_permits(params)
    return PermitsSearchResponse(page=page, limit=limit, total=total, permits=permits)


@router.get("/permits/{permit_id}", response_model=Permit,
            summary="Full permit detail with enrichment + source links")
def get_permit(
    permit_id: str,
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(get_api_key_context),  # noqa: B008
) -> Permit:
    p = repo.get_permit(permit_id)
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": {"code": "not_found", "message": f"Permit '{permit_id}' not found.",
                      "docs_url": "https://docs.permy.dev/permits"}})
    return p


@router.get("/properties/resolve", response_model=Property,
            summary="Normalize an address → jurisdiction, city/county, parcel hints, coverage status")
def resolve_property(
    address: str = Query(..., description="Full street address, e.g. '10912 Mystic Timber Dr, Austin, TX 78754'"),
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(get_api_key_context),  # noqa: B008
) -> Property:
    prop = repo.resolve_property(address)
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": {"code": "property_not_found",
                      "message": "Address not yet indexed. It may be outside current coverage.",
                      "docs_url": "https://docs.permy.dev/coverage"}})
    return prop


@router.get("/properties/{property_id}/timeline", response_model=PropertyTimeline,
            summary="Full permit history for an address")
def property_timeline(
    property_id: str,
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(get_api_key_context),  # noqa: B008
) -> PropertyTimeline:
    tl = repo.property_timeline(property_id)
    if not tl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": {"code": "property_not_found",
                      "message": f"No property/timeline for '{property_id}'.",
                      "docs_url": "https://docs.permy.dev/properties"}})
    return tl
