from __future__ import annotations

"""Permy domain models — the unified, cross-city normalization contract.

These are the source of truth for the OpenAPI 3.1 spec (FastAPI generates it).
Every record must use explicit `null` for missing fields — never omit — so
downstream apps and agents can rely on schema stability across cities.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from permy.core.config import PERSONAS, RECOMMENDED_ACTIONS, TRADES, WORK_CLASSES

# ---- shared enums (Literal tuples so OpenAPI emits proper enums) ----
TradeCategory = Literal[
    "roofing", "solar", "hvac", "plumbing", "electrical",
    "building", "general", "demolition", "other", "unknown",
]
WorkClass = Literal[
    "new_construction", "alteration", "addition", "remodel",
    "repair", "demolition", "other", "unknown",
]
PermitStatus = Literal[
    "applied", "issued", "active", "final", "expired",
    "cancelled", "withdrawn", "unknown",
]
RecommendedAction = Literal["call_now", "qualify", "monitor", "skip"]
Persona = Literal["roofer", "solar", "hvac", "investor", "supplier", "insurer", "general"]
SortDir = Literal["asc", "desc"]


class PermyModel(BaseModel):
    """Base: explicit nulls, forbidden unknown fields, ISO datetimes."""
    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=False,
        extra="forbid",
        ser_json_unset="null",
    )


# ---------------------------------------------------------------------------
# Address + geocoding
# ---------------------------------------------------------------------------
class Address(PermyModel):
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    full: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocode_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Parties
# ---------------------------------------------------------------------------
class ContractorRef(PermyModel):
    """Contractor as attached to a permit (denormalized summary)."""
    id: Optional[str] = None
    name: Optional[str] = None
    license: Optional[str] = None
    license_state: Optional[str] = None
    license_status: Optional[str] = None
    trade: Optional[str] = None
    phone: Optional[str] = None


class OwnerRef(PermyModel):
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# Enrichment (attached to every permit)
# ---------------------------------------------------------------------------
class Enrichment(PermyModel):
    lead_score: Optional[int] = Field(None, ge=0, le=100, description="0–100 lead score")
    recommended_action: Optional[RecommendedAction] = None
    reason: Optional[str] = Field(None, description="Human-readable explanation of top factors")
    dq_flags: List[str] = Field(default_factory=list, description="Data-quality flags")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Source+freshness+completeness")


# ---------------------------------------------------------------------------
# Permit — the canonical cross-city record
# ---------------------------------------------------------------------------
class PermitDates(PermyModel):
    applied: Optional[date] = None
    issued: Optional[date] = None
    finaled: Optional[date] = None
    expired: Optional[date] = None


class Permit(PermyModel):
    id: str = Field(..., description="Permy opaque id (stringified bigint)")
    canonical_uid: str = Field(..., description="Stable hash(jurisdiction + source_permit_id)")
    jurisdiction_slug: str
    source_permit_id: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    last_checked_at: datetime

    address: Address
    permit_type_raw: Optional[str] = None
    permit_type_normalized: Optional[str] = None
    work_class: WorkClass = "unknown"
    trade_category: TradeCategory = "unknown"
    is_new_construction: bool = False
    is_alteration: bool = False
    is_demolition: bool = False

    valuation_usd: Optional[float] = Field(None, description="Declared job value in USD; null when city doesn't publish")
    housing_units: Optional[int] = None
    new_add_sqft: Optional[int] = None

    dates: PermitDates = Field(default_factory=PermitDates)
    current_status: PermitStatus = "unknown"
    status_raw: Optional[str] = None
    description: Optional[str] = None
    description_enriched: Optional[str] = None

    contractor: Optional[ContractorRef] = None
    owner: Optional[OwnerRef] = None
    parcel_id: Optional[str] = None

    enrichment: Enrichment = Field(default_factory=Enrichment)


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------
class Property(PermyModel):
    id: str
    canonical_uid: str
    full_address: str
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocode_confidence: Optional[float] = None
    jurisdiction_slug: Optional[str] = None
    parcel_id: Optional[str] = None
    year_built: Optional[int] = None
    sqft: Optional[int] = None
    permit_count: int = 0
    last_permit_date: Optional[date] = None
    coverage_status: Literal["covered", "partial", "no_feed"] = "covered"


class PermitTimelineEntry(PermyModel):
    """A permit rolled up for property timeline views."""
    id: str
    permit_type_normalized: Optional[str] = None
    work_class: WorkClass = "unknown"
    trade_category: TradeCategory = "unknown"
    valuation_usd: Optional[float] = None
    issued_date: Optional[date] = None
    current_status: PermitStatus = "unknown"
    contractor: Optional[ContractorRef] = None
    description: Optional[str] = None


class PropertyTimeline(PermyModel):
    property: Property
    permits: List[PermitTimelineEntry]
    total_permits: int
    total_valuation_usd: Optional[float] = None
    last_activity: Optional[date] = None
    unpermitted_work_flag: bool = False


# ---------------------------------------------------------------------------
# Contractor (full)
# ---------------------------------------------------------------------------
class Contractor(PermyModel):
    id: str
    canonical_uid: str
    name: str
    license_number: Optional[str] = None
    license_state: Optional[str] = None
    license_status: Optional[str] = None
    trade: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    source_url: Optional[str] = None
    confidence: float = 0.0


class ContractorActivity(PermyModel):
    contractor: Contractor
    permit_count: int = 0
    total_valuation_usd: float = 0.0
    trade_mix: Dict[str, int] = Field(default_factory=dict)
    active_cities: List[str] = Field(default_factory=list)
    value_band: Optional[Literal["<50k", "50k-500k", "500k+"]] = None
    momentum: float = Field(0.0, ge=0.0, le=1.0, description="Recent activity intensity 0–1")
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Market (ZIP development score)
# ---------------------------------------------------------------------------
class MarketScore(PermyModel):
    zip: str
    as_of_date: date
    permit_count_30d: int
    permit_count_90d: int
    total_value_30d: float
    total_value_90d: float
    trade_mix: Dict[str, int] = Field(default_factory=dict)
    mom_delta_pct: Optional[float] = Field(None, description="Month-over-month permit volume %")
    top_contractors: List[Dict[str, Any]] = Field(default_factory=list)
    hotspot_score: int = Field(..., ge=0, le=100, description="ZIP development momentum 0–100")
    narrative: Optional[str] = Field(None, description="One-line human summary")


# ---------------------------------------------------------------------------
# Lead ranking
# ---------------------------------------------------------------------------
class RankedLead(PermyModel):
    permit: Permit
    lead_score: int = Field(..., ge=0, le=100)
    recommended_action: RecommendedAction
    reason: str
    persona: Persona


class RankedLeadsResponse(PermyModel):
    persona: Persona
    page: int
    limit: int
    total: int
    leads: List[RankedLead]


# ---------------------------------------------------------------------------
# Intelligence bundle (POST /v1/intelligence/score)
# ---------------------------------------------------------------------------
class IntelligenceRequest(PermyModel):
    address: Optional[str] = None
    permit_id: Optional[str] = None
    persona: Persona = "general"
    project_type: Optional[str] = None


class RiskFlag(PermyModel):
    flag: str
    severity: Literal["info", "warning", "critical"]
    detail: Optional[str] = None


class IntelligenceResponse(PermyModel):
    input: IntelligenceRequest
    property: Optional[Property] = None
    permits: List[Permit] = Field(default_factory=list)
    development_score: int = Field(..., ge=0, le=100)
    permit_activity: Dict[str, Any] = Field(default_factory=dict)
    risk_flags: List[RiskFlag] = Field(default_factory=list)
    market_context: Optional[str] = None
    market: Optional[MarketScore] = None
    recommended_action: Optional[RecommendedAction] = None
    lead_score: Optional[int] = Field(None, ge=0, le=100)
    source_links: List[str] = Field(default_factory=list)
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Pagination + search params
# ---------------------------------------------------------------------------
class PageMeta(PermyModel):
    page: int = Field(1, ge=1)
    limit: int = Field(25, ge=1, le=100)
    total: int = 0


class PermitsSearchResponse(PermyModel):
    page: int
    limit: int
    total: int
    permits: List[Permit]


class ContractorsSearchResponse(PermyModel):
    page: int
    limit: int
    total: int
    contractors: List[Contractor]


# ---------------------------------------------------------------------------
# Alerts + webhooks
# ---------------------------------------------------------------------------
class AlertCreate(PermyModel):
    persona: Persona = "general"
    query: Dict[str, Any] = Field(..., description="Same params shape as /v1/permits/search")
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None


class Alert(PermyModel):
    id: str
    persona: Persona
    query: Dict[str, Any]
    webhook_url: Optional[str] = None
    is_active: bool = True
    last_fired_at: Optional[datetime] = None
    created_at: datetime


class WebhookTestRequest(PermyModel):
    url: str
    secret: Optional[str] = None


class WebhookTestResponse(PermyModel):
    delivered: bool
    status_code: Optional[int] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------
class CoverageCity(PermyModel):
    jurisdiction_slug: str
    city: str
    state: str
    source_portal: str
    source_name: str
    is_live: bool
    last_ingested_at: Optional[datetime] = None
    ingest_cadence: str
    fields: Dict[str, Union[bool, str]] = Field(
        default_factory=lambda: {
            "permits": True, "valuation": False, "contractor": False,
            "owner": False, "phone": False, "geocode": False,
        },
        description="true / false / 'partial' — honestly notes where a city "
                    "publishes a field only sometimes (e.g. owner via contact list).",
    )


class CoverageResponse(PermyModel):
    cities: List[CoverageCity]
    total: int


# ---------------------------------------------------------------------------
# Health + usage
# ---------------------------------------------------------------------------
class HealthResponse(PermyModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    version: str
    time: datetime
    db: Optional[Literal["ok", "down"]] = None
    redis: Optional[Literal["ok", "down"]] = None
    coverage_cities: int = 0


class UsageResponse(PermyModel):
    api_key: str
    tier: str
    day: date
    requests_today: int
    daily_limit: Optional[int] = None
    monthly_limit: Optional[int] = None
    month_requests: int = 0


# ---------------------------------------------------------------------------
# Error envelope (one shape everywhere)
# ---------------------------------------------------------------------------
class ErrorDetail(PermyModel):
    code: str = Field(..., description="Stable machine code, e.g. 'rate_limited'")
    message: str
    field: Optional[str] = None
    docs_url: Optional[str] = "https://docs.permy.dev/errors"


class ErrorResponse(PermyModel):
    error: ErrorDetail
    request_id: Optional[str] = None
