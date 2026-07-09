from __future__ import annotations

"""Leads + intelligence endpoints (8–9). Pro-tier gated."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from permy.db.repo import Repo, get_repo
from permy.middleware.auth import ApiKeyContext, require_feature
from permy.models.schemas import (
    IntelligenceRequest, IntelligenceResponse, RankedLeadsResponse,
)

router = APIRouter(prefix="/v1", tags=["leads & intelligence"])


@router.get("/leads/ranked", response_model=RankedLeadsResponse,
            summary="Ranked opportunities for a buyer persona with lead_score + recommended_action + reason")
def leads_ranked(
    persona: str = Query("general", pattern="^(roofer|solar|hvac|investor|supplier|insurer|general)$"),
    city: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    zip: Optional[str] = Query(None),
    trade: Optional[str] = Query(None),
    min_valuation: Optional[float] = Query(None, ge=0),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(require_feature("leads")),  # noqa: B008
) -> RankedLeadsResponse:
    params = {k: v for k, v in dict(
        persona=persona, city=city, state=state, zip=zip, trade=trade,
        min_valuation=min_valuation, page=page, limit=limit,
    ).items() if v is not None}
    leads, total = repo.rank_leads(params)
    return RankedLeadsResponse(persona=persona, page=page, limit=limit, total=total, leads=leads)


@router.post("/intelligence/score", response_model=IntelligenceResponse,
             summary="Address or permit_id + persona → development_score, risk_flags, market narrative, sources")
def intelligence_score(
    body: IntelligenceRequest,
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(require_feature("intel")),  # noqa: B008
) -> IntelligenceResponse:
    return repo.intelligence(body)
