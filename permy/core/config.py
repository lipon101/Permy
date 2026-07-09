from __future__ import annotations

"""Core config & constants for Permy."""
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PERMY_ env vars
    env: str = "local"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    base_url: str = "http://localhost:8000"

    api_keys: str = "dev-key-1"
    admin_keys: str = ""

    webhook_secret: str = "change-me"

    database_url: str = "postgresql+asyncpg://permy:permy@localhost:5432/permy"
    redis_url: str = "redis://localhost:6379/0"

    rate_limit_free: int = 60
    rate_limit_paid: int = 600

    # sample mode (no-key docs playground): caps drive the funnel → paid conversion
    sample_max_per_response: int = 10
    sample_daily_limit: int = 30

    enable_webhooks: bool = True
    enable_mcp: bool = True

    # ---- non-PERMY_ env vars (aliased) ----
    geocoder_provider: str = Field("census", alias="GEOCODER_PROVIDER")
    smarty_auth_id: str = Field("", alias="SMARTY_AUTH_ID")
    smarty_auth_token: str = Field("", alias="SMARTY_AUTH_TOKEN")
    mapbox_api_token: str = Field("", alias="MAPBOX_API_TOKEN")
    socrata_app_token: str = Field("", alias="SOCRATA_APP_TOKEN")

    model_config = SettingsConfigDict(env_prefix="PERMY_", env_file=".env", extra="ignore")

    @property
    def api_key_set(self) -> set:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def admin_key_set(self) -> set:
        return {k.strip() for k in self.admin_keys.split(",") if k.strip()}


settings = Settings()


# ---- tiers (mirror RapidAPI pricing) ----
TIER_LIMITS = {
    "free":     {"daily": 100,       "monthly": None,   "saved_searches": 1,   "webhooks": False, "export": False, "leads": False, "intel": False},
    "starter":  {"daily": None,      "monthly": 2000,   "saved_searches": 0,   "webhooks": False, "export": False, "leads": False, "intel": False},
    "builder":  {"daily": None,      "monthly": 10000,  "saved_searches": 5,   "webhooks": False, "export": True,  "leads": False, "intel": False},
    "pro":      {"daily": None,      "monthly": 100000, "saved_searches": 50,  "webhooks": True,  "export": True,  "leads": True,  "intel": True},
    "business": {"daily": None,      "monthly": 500000, "saved_searches": 500, "webhooks": True,  "export": True,  "leads": True,  "intel": True},
    "enterprise": {"daily": None,    "monthly": None,   "saved_searches": -1,  "webhooks": True,  "export": True,  "leads": True,  "intel": True},
}

PERSONAS = ["roofer", "solar", "hvac", "investor", "supplier", "insurer", "general"]

TRADES = [
    "roofing", "solar", "hvac", "plumbing", "electrical",
    "building", "general", "demolition", "other", "unknown",
]

WORK_CLASSES = [
    "new_construction", "alteration", "addition", "remodel",
    "repair", "demolition", "other", "unknown",
]

PERMIT_STATUSES = [
    "applied", "issued", "active", "final", "expired",
    "cancelled", "withdrawn", "unknown",
]

RECOMMENDED_ACTIONS = ["call_now", "qualify", "monitor", "skip"]

# Canonical trade keyword maps (used by ingest.classify).
# Order matters: first match wins. Keep specific terms above generic ones.
TRADE_KEYWORDS = {
    "roofing":   ["roof", "shingle", "rafter", "underlayment", "gutter", "skylight"],
    "solar":     ["solar", "photovoltaic", "pv array", "panel"],
    "hvac":      ["hvac", "mechanical", "air condition", "furnace", "duct", "heating", "cooling", "ventilation"],
    "plumbing":  ["plumb", "sewer", "water heater", "backflow", "irrigation"],
    "electrical":["electr", "panel upgrade", "service upgrade", "wiring"],
    "demolition":["demolit", "demolish", "tear down", "raz"],
    "building":  ["building", "new construction", "addition", "remodel", "tenant finish", "tenant build"],
    "general":   ["general", "contractor", "builder"],
}

# Map Austin Socrata permittype codes → normalized permit_type
AUSTIN_PERMITTYPE_MAP = {
    "BP": "Building Permit",
    "EP": "Electrical Permit",
    "MP": "Mechanical Permit",
    "PP": "Plumbing Permit",
    "RP": "Residential Permit",
}

# Map Austin work_class strings → normalized work_class enum
AUSTIN_WORKCLASS_MAP = {
    "new": "new_construction",
    "addition": "addition",
    "remodel": "remodel",
    "repair": "repair",
    "demolition": "demolition",
    "homebuilder loop": "remodel",  # Austin-specific; treat as remodel-level work
}

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
