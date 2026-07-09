# Permy — 4-Week Sprint Plan

> From empty repo to a paid RapidAPI listing with 3 live cities, lead scoring, webhooks, docs, and an MCP server. Two-engineer team (1 backend, 1 data/infra). Tickets are written as GitHub issues — copy-paste ready.

## Sprint 1 (Week 1) — Foundation + Austin live

**Goal:** repo, API skeleton, auth, rate-limit, health/usage, CI, and the Austin adapter feeding `/permits/search` + `/permits/{id}` with real data.

| # | Ticket | Acceptance criteria |
|---|---|---|
| S1-1 | Scaffold repo + tooling | `pyproject.toml`, Dockerfile, docker-compose (pg+postgis+redis), Makefile, CI (lint+test+pg/redis services), `.env.example`, README. `make test` green from main. |
| S1-2 | Postgres + PostGIS schema | `permy/db/schema.sql` idempotent; all enums + tables + indexes + GiST + serving view. Runs clean on `postgis/postgis:16`. |
| S1-3 | Core domain models (Pydantic v2) | `Permit`, `Address`, `Contractor`, `Property`, `MarketScore`, `RankedLead`, `IntelligenceResponse`, `ErrorResponse` with `extra="forbid"` + explicit-null. Unit tests assert every required key always serializes. |
| S1-4 | CityAdapter Protocol + Austin adapter | `permy/adapters/base.py` Protocol; `AustinAdapter` hits `3syk-w9eu`, `normalize()` maps all real fields. Tests use recorded Socrata fixture (no live calls in CI). |
| S1-5 | In-memory Repo + seeding | `permy/db/repo.py` seeds from Austin fixture so API works with zero infra. PG-backed Repo stubbed behind same interface. |
| S1-6 | FastAPI app + auth + rate-limit | `X-API-Key` + Bearer + RapidAPI header; tier-aware token-bucket rate limit; unified `{error:...}` envelope; `/v1/health` + `/v1/usage`. OpenAPI 3.1 at `/openapi.json`. |
| S1-7 | `/v1/permits/search` + `/v1/permits/{id}` live | All filters (city/state/zip/trade/type/status/date/value/contractor/keyword/bbox), pagination, sort. Integration tests green. |

**Definition of done for Sprint 1:** `curl /v1/permits/search?city=Austin` returns real Austin permits; 83+ tests green; CI green.

## Sprint 2 (Week 2) — NYC + Chicago, properties, contractors, enrichment

**Goal:** 3 cities live; property timeline + contractor endpoints; geocoding, classification, license join wired into the pipeline.

| # | Ticket | Acceptance criteria |
|---|---|---|
| S2-1 | NYC DOB adapter | `NYCDobAdapter` (Socrata BIS feed); `normalize()` maps NYC fields → `Permit`; tests with recorded fixture. `/coverage` shows NYC. |
| S2-2 | Chicago adapter | `ChicagoAdapter` (City of Chicago Socrata `ydr8-5enu` or current permit dataset); fixture tests. 3 cities in `/coverage`. |
| S2-3 | Census geocoder in pipeline | `permy/ingest/geocode.py`; pipeline geocodes addresses with no lat/lng; `geocode_confidence` set; failures degrade gracefully (no crash). |
| S2-4 | Trade classifier | `permy/ingest/classify.py` keyword maps; pipeline re-classifies `unknown` trades; measured ≥80% of described records get a non-unknown trade. |
| S2-5 | License-board join (TX + CA) | `LicenseBoard` Protocol; TX TRCC + CA CSLB adapters (best-effort, never block); `contractor.license_status` populated where joinable. |
| S2-6 | Dedupe via canonical_uid | `canonical_permit_uid` = hash(jurisdiction+source_id); UPSERT-on-conflict in PG Repo; re-ingest doesn't duplicate. |
| S2-7 | `/v1/properties/resolve` + `/v1/properties/{id}/timeline` | Address normalization → property; full permit history sorted desc, categorized; integration tests. |
| S2-8 | `/v1/contractors/search` + `/v1/contractors/{id}/activity` | Name/license/city/trade search; activity = count, trade mix, active cities, value band, momentum; tests. |
| S2-9 | Confidence on every record | `overall_confidence` (source+freshness+completeness) populated by pipeline; surfaced in `enrichment.confidence`. |

**DoD Sprint 2:** 3 cities daily-fresh; property timeline + contractor activity return real data; re-ingest is idempotent.

## Sprint 3 (Week 3) — Lead scoring, intelligence, markets, alerts, webhooks

**Goal:** the differentiators are live — persona-ranked leads, the intelligence bundle, ZIP development scores, and signed webhooks.

| # | Ticket | Acceptance criteria |
|---|---|---|
| S3-1 | Deterministic lead_score module | `permy/scoring/lead_score.py`; 6 components, 7 persona presets (weights sum to 100), bands→action, human `reason`, `dq_flags`. 28+ unit tests green (already done in scaffold). |
| S3-2 | `/v1/leads/ranked` (Pro-gated) | Persona + filters → ranked `RankedLead[]`; `reason` explains top factors; Pro-tier gating enforced (403 for free). |
| S3-3 | `/v1/intelligence/score` (Pro-gated) | `{address\|permit_id, persona, project_type}` → development_score, permit_activity, risk_flags, market_context, source_links, confidence. |
| S3-4 | `/v1/markets/{zip}/development-score` | Nightly rollup recompute; permit_count_30d/90d, total_value, trade_mix, mom_delta_pct, top_contractors, hotspot_score 0–100, narrative. |
| S3-5 | Alerts CRUD | `POST/GET/DELETE /v1/alerts`; saved-search quota per tier; owner-scoped. |
| S3-6 | Signed webhook delivery | HMAC-SHA256 in `X-Permy-Signature`; `X-Permy-Event` header; arq `deliver_webhook` job with 30s/2m/10m backoff + dead-letter; `/v1/webhooks/test` for dry-run. |
| S3-7 | Alert matcher | After each ingest, match new permits against active alerts; enqueue `deliver_webhook` for matches. |
| S3-8 | Nightly rollups worker | arq cron recomputes `markets` + contractor aggregates; cached reads. |

**DoD Sprint 3:** a roofer can call `/leads/ranked?persona=roofer` and get `call_now` leads with reasons; a webhook fires on a new roofing permit within 60s.

## Sprint 4 (Week 4) — Docs, RapidAPI launch, MCP, pricing enforcement

**Goal:** public docs + playground, RapidAPI listing live, MCP server published, free-tier quotas enforced, soft launch.

| # | Ticket | Acceptance criteria |
|---|---|---|
| S4-1 | Docs site (Mintlify) | OpenAPI-driven API reference + interactive playground (sample mode, no key); Quickstart, Concepts (normalized schema, lead scoring, personas, webhooks, rate limits, freshness, confidence), honest Coverage table. |
| S4-2 | Coverage page (honest) | Per-city ✅/❌/partial for permits/valuation/contractor/owner/phone/geocode; `last_ingested_at`; "request a city" form. |
| S4-3 | RapidAPI listing | Title/subtitle/description/tags/5 code examples/pricing cards pasted from `docs/RAPIDAPI_LISTING.md`; provider portal configured; test key works end-to-end. |
| S4-4 | Pricing-tier enforcement | Free 100/day + 1 saved search; Starter/Builder/Pro/Business quotas; overage billing flag; annual discount flag. Quota counters in `usage_daily`. |
| S4-5 | MCP server published | 5 tools (search_permits, property_timeline, contractor_activity, zip_development_score, rank_leads); stdio server; listed on Smithery + Glama + Claude tools registry; Business-tier gating. |
| S4-6 | Node + Python SDKs (thin) | `permy-sdk` (npm) + `permy-sdk` (PyPI) wrapping the REST surface; typed; quickstart examples work. |
| S4-7 | Observability | p95 latency + uptime dashboards; `/v1/health` probes DB+Redis; alert on ingest failures (city feed dark). |
| S4-8 | Trademark + domain check | USPTO search for "Permy"; secure permy.com/.io/.app (fallbacks Permio/Permi ready). |
| S4-9 | Soft launch | Listing live on RapidAPI; post to 2-3 relevant communities; free-tier SEO traffic starts. |

**DoD Sprint 4 (launch):** RapidAPI listing is live and discoverable; a developer can go from subscribe → first `call_now` lead → webhook in under 10 minutes; MCP server usable from Claude.

---

## After launch (ongoing, Phase 7+)
- Add 1–2 cities per week toward 25 by month 6.
- FEMA NFHL flood overlay → insurer risk enrichment.
- LLM `description_enriched` pass for uncertain records (behind flag).
- Bulk export + Snowflake/BigQuery delivery for Business/Enterprise.
- Programmatic content: per-city pages ("Building permits in {City}", "Top contractors in {City}") that rank and link into the API.
- Comparison posts (PermitStack vs Permy, PermitRadar vs Permy) — honest, useful.
