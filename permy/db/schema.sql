-- ============================================================================
-- Permy — PostgreSQL + PostGIS schema
-- Idempotent: safe to run on an empty or existing DB. Designed for Postgres 16 + PostGIS 3.4
-- Medallion layout: raw landing → silver/clean → serving views.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy contractor/address search

-- ---------------------------------------------------------------------------
-- enums
-- ---------------------------------------------------------------------------
DO $$ BEGIN
  CREATE TYPE permit_status AS ENUM ('applied','issued','active','final','expired','cancelled','withdrawn','unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE work_class AS ENUM ('new_construction','alteration','addition','remodel','repair','demolition','other','unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE trade_category AS ENUM ('roofing','solar','hvac','plumbing','electrical','building','general','demolition','other','unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE recommended_action AS ENUM ('call_now','qualify','monitor','skip');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE persona_kind AS ENUM ('roofer','solar','hvac','investor','supplier','insurer','general');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- jurisdictions & coverage
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jurisdictions (
  jurisdiction_slug    TEXT PRIMARY KEY,           -- e.g. 'austin-tx'
  city                 TEXT NOT NULL,
  state                TEXT NOT NULL,
  county               TEXT,
  source_portal        TEXT NOT NULL,               -- 'socrata' | 'arcgis' | 'accela' | 'tyler' | 'ckan' | 'custom'
  source_name          TEXT NOT NULL,               -- human label
  source_home_url      TEXT,
  is_live              BOOLEAN NOT NULL DEFAULT TRUE,
  last_ingested_at     TIMESTAMPTZ,
  ingest_cadence       TEXT NOT NULL DEFAULT 'daily',
  coverage             JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {permits:true, valuation:true, contractor:true, owner:false, phone:true}
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RAW landing (one row per upstream record, kept for replay/audit)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_permits (
  id                   BIGSERIAL PRIMARY KEY,
  jurisdiction_slug    TEXT NOT NULL REFERENCES jurisdictions(jurisdiction_slug),
  source_permit_id     TEXT NOT NULL,               -- upstream native id (e.g. project_id)
  source_url           TEXT,
  raw_payload          JSONB NOT NULL,              -- verbatim upstream record
  fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (jurisdiction_slug, source_permit_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_permits_juris ON raw_permits(jurisdiction_slug);
CREATE INDEX IF NOT EXISTS idx_raw_permits_fetched ON raw_permits(fetched_at DESC);

-- ---------------------------------------------------------------------------
-- SILVER: normalized permits (the clean cross-city schema)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permits (
  id                   BIGSERIAL PRIMARY KEY,
  canonical_uid        TEXT NOT NULL UNIQUE,        -- stable hash(jurisdiction_slug + source_permit_id)
  jurisdiction_slug    TEXT NOT NULL REFERENCES jurisdictions(jurisdiction_slug),
  source_permit_id     TEXT NOT NULL,
  source_url           TEXT,
  source_name          TEXT,
  first_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- address
  street               TEXT,
  city                 TEXT,
  state                TEXT,
  zip                  TEXT,
  full_address         TEXT,
  geom                 GEOGRAPHY(POINT, 4326),
  geocode_confidence   REAL,                        -- 0..1

  -- classification
  permit_type_raw      TEXT,
  permit_type_normalized TEXT,
  work_class           work_class NOT NULL DEFAULT 'unknown',
  trade_category       trade_category NOT NULL DEFAULT 'unknown',
  is_new_construction  BOOLEAN NOT NULL DEFAULT FALSE,
  is_alteration        BOOLEAN NOT NULL DEFAULT FALSE,
  is_demolition        BOOLEAN NOT NULL DEFAULT FALSE,

  -- economics
  valuation_usd        NUMERIC(14,2),
  housing_units        INTEGER,
  new_add_sqft         INTEGER,

  -- dates
  applied_date         DATE,
  issued_date          DATE,
  finaled_date         DATE,
  expired_date         DATE,
  current_status       permit_status NOT NULL DEFAULT 'unknown',
  status_raw           TEXT,

  -- text
  description          TEXT,
  description_enriched TEXT,                          -- optional LLM-refined

  -- parties (FK to parties table below)
  contractor_id        BIGINT REFERENCES contractors(id),
  owner_name           TEXT,
  parcel_id            TEXT,                          -- e.g. tcad_id

  -- enrichment
  lead_score           SMALLINT,                      -- 0..100
  recommended_action   recommended_action,
  reason               TEXT,
  dq_flags             JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence           REAL NOT NULL DEFAULT 0.0,    -- 0..1

  UNIQUE (jurisdiction_slug, source_permit_id)
);

CREATE INDEX IF NOT EXISTS idx_permits_city    ON permits(city);
CREATE INDEX IF NOT EXISTS idx_permits_state   ON permits(state);
CREATE INDEX IF NOT EXISTS idx_permits_zip     ON permits(zip);
CREATE INDEX IF NOT EXISTS idx_permits_trade   ON permits(trade_category);
CREATE INDEX IF NOT EXISTS idx_permits_status  ON permits(current_status);
CREATE INDEX IF NOT EXISTS idx_permits_issued  ON permits(issued_date DESC);
CREATE INDEX IF NOT EXISTS idx_permits_val     ON permits(valuation_usd DESC);
CREATE INDEX IF NOT EXISTS idx_permits_score   ON permits(lead_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_permits_geom    ON permits USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_permits_contractor ON permits(contractor_id);
CREATE INDEX IF NOT EXISTS idx_permits_addr_trgm ON permits USING GIN (full_address gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_permits_desc_trgm  ON permits USING GIN (description gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_permits_juris_source ON permits(jurisdiction_slug, source_permit_id);

-- ---------------------------------------------------------------------------
-- contractors (normalized party)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contractors (
  id                   BIGSERIAL PRIMARY KEY,
  canonical_uid        TEXT NOT NULL UNIQUE,        -- hash(jurisdiction_slug + normalized name + license?)
  jurisdiction_slug    TEXT NOT NULL REFERENCES jurisdictions(jurisdiction_slug),
  name                 TEXT NOT NULL,
  license_number       TEXT,
  license_state        TEXT,
  license_status       TEXT,                          -- 'active'|'expired'|'unknown' from license board join
  trade                TEXT,
  phone                TEXT,
  city                 TEXT,
  state                TEXT,
  zip                  TEXT,
  permit_count         INTEGER NOT NULL DEFAULT 0,
  total_valuation_usd  NUMERIC(14,2) NOT NULL DEFAULT 0,
  active_cities        JSONB NOT NULL DEFAULT '[]'::jsonb,
  trade_mix            JSONB NOT NULL DEFAULT '{}'::jsonb,
  value_band           TEXT,                          -- '<50k'|'50k-500k'|'500k+' derived
  momentum             REAL NOT NULL DEFAULT 0.0,    -- recent activity score 0..1
  confidence           REAL NOT NULL DEFAULT 0.0,
  first_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_url           TEXT
);
CREATE INDEX IF NOT EXISTS idx_contractors_name_trgm ON contractors USING GIN (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_contractors_license   ON contractors(license_number);
CREATE INDEX IF NOT EXISTS idx_contractors_trade     ON contractors(trade);

-- ---------------------------------------------------------------------------
-- properties (address-canonical, anchors timelines)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS properties (
  id                   BIGSERIAL PRIMARY KEY,
  canonical_uid        TEXT NOT NULL UNIQUE,         -- hash(normalized full_address)
  full_address         TEXT NOT NULL,
  street               TEXT,
  city                 TEXT,
  state                TEXT,
  zip                  TEXT,
  geom                 GEOGRAPHY(POINT, 4326),
  geocode_confidence   REAL,
  jurisdiction_slug    TEXT REFERENCES jurisdictions(jurisdiction_slug),
  parcel_id            TEXT,
  year_built           INTEGER,
  sqft                 INTEGER,
  permit_count         INTEGER NOT NULL DEFAULT 0,
  last_permit_date     DATE,
  coverage_status      TEXT NOT NULL DEFAULT 'covered',  -- 'covered'|'partial'|'no_feed'
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_properties_addr_trgm ON properties USING GIN (full_address gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_properties_geom      ON properties USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_properties_zip       ON properties(zip);

-- ---------------------------------------------------------------------------
-- markets: rolling ZIP-level aggregates (recomputed nightly)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS markets (
  id                   BIGSERIAL PRIMARY KEY,
  zip                  TEXT NOT NULL,
  as_of_date           DATE NOT NULL,
  permit_count_30d     INTEGER NOT NULL DEFAULT 0,
  permit_count_90d     INTEGER NOT NULL DEFAULT 0,
  total_value_30d      NUMERIC(14,2) NOT NULL DEFAULT 0,
  total_value_90d      NUMERIC(14,2) NOT NULL DEFAULT 0,
  trade_mix            JSONB NOT NULL DEFAULT '{}'::jsonb,
  mom_delta_pct        REAL,                          -- month-over-month permit volume %
  top_contractors      JSONB NOT NULL DEFAULT '[]'::jsonb,
  hotspot_score        SMALLINT NOT NULL DEFAULT 0,  -- 0..100
  UNIQUE (zip, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_markets_zip_date ON markets(zip, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_markets_hot      ON markets(hotspot_score DESC);

-- ---------------------------------------------------------------------------
-- alerts (saved searches) + webhook deliveries
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
  id                   BIGSERIAL PRIMARY KEY,
  api_key              TEXT NOT NULL,                -- owner
  persona              persona_kind NOT NULL DEFAULT 'general',
  query                JSONB NOT NULL,               -- same shape as /permits/search params
  webhook_url          TEXT,
  webhook_secret       TEXT,
  last_fired_at        TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_active            BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_alerts_owner ON alerts(api_key);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id                   BIGSERIAL PRIMARY KEY,
  alert_id             BIGINT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
  payload              JSONB NOT NULL,
  attempt             SMALLINT NOT NULL DEFAULT 0,
  status              TEXT NOT NULL DEFAULT 'queued', -- 'queued'|'sent'|'failed'|'dead'
  response_code       INTEGER,
  sent_at             TIMESTAMPTZ,
  next_retry_at       TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_webhooks_status ON webhook_deliveries(status, next_retry_at);

-- ---------------------------------------------------------------------------
-- usage / quotas (per API key, per day)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_daily (
  api_key              TEXT NOT NULL,
  day                 DATE NOT NULL,
  tier                TEXT NOT NULL DEFAULT 'free',
  requests            INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (api_key, day)
);

-- ---------------------------------------------------------------------------
-- serving views
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_permits_full AS
SELECT
  p.*,
  c.name AS contractor_name, c.license_number, c.trade AS contractor_trade, c.phone AS contractor_phone,
  j.city AS jurisdiction_city, j.source_name AS jurisdiction_source
FROM permits p
LEFT JOIN contractors c ON c.id = p.contractor_id
LEFT JOIN jurisdictions j ON j.jurisdiction_slug = p.jurisdiction_slug;
