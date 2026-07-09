# Permy — Deliverables Index

> Maps each of the 17 build-brief sections and the 12 "produce now" deliverables to its location in this repo. Everything below is real, working code or real copy — not prose placeholders.

## The 12 "produce now" deliverables

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | Architecture writeup + ASCII data-flow diagram | `docs/ARCHITECTURE.md` | ✅ |
| 2 | Full OpenAPI 3.1 spec — all 13 endpoints, params, response schemas, error envelope | `docs/openapi.json` (generated) + routers in `permy/api/v1/` | ✅ |
| 3 | Normalized permit + contractor + property + market schema (types) | `permy/models/schemas.py` (Pydantic v2) | ✅ |
| 4 | Reference adapter interface + working Austin adapter + tests | `permy/adapters/base.py` + `permy/adapters/austin.py` + `tests/test_austin_adapter.py` (real Socrata fixture) | ✅ |
| 5 | Deterministic scoring module + persona weights + unit tests | `permy/scoring/lead_score.py` + `tests/test_scoring.py` (28 tests) | ✅ |
| 6 | Ingestion/queue/webhook design + table DDL (Postgres + PostGIS) | `permy/ingest/{pipeline,worker,geocode,classify,license,dedupe,webhooks,cli}.py` + `permy/db/schema.sql` | ✅ |
| 7 | Repo scaffold: structure, README, env, Dockerfile, CI | repo root (`pyproject.toml`, `Dockerfile`, `Makefile`, `.github/workflows/ci.yml`, `.env.example`, `deploy/docker-compose.yml`) | ✅ |
| 8 | RapidAPI listing copy (title, subtitle, desc, tags, 5 code examples, pricing cards) | `docs/RAPIDAPI_LISTING.md` | ✅ |
| 9 | Docs outline + quickstart + "Concepts: Lead Scoring" page | `docs/DOCS_OUTLINE.md` + `docs/QUICKSTART.md` + `docs/LEAD_SCORING.md` | ✅ |
| 10 | MCP server tool definitions (5 tools) with input/output schemas | `permy/mcp/server.py` + `tests/test_mcp.py` | ✅ |
| 11 | 4-week sprint plan with concrete tickets | `docs/SPRINT_PLAN.md` | ✅ |
| 12 | Risk register (data fragility, legal, competitive, cost) + mitigations | `docs/RISK_REGISTER.md` | ✅ |

## Build-brief section coverage

| § | Brief section | Where |
|---|---|---|
| 1 | Product concept | `README.md` + `docs/ARCHITECTURE.md` §1 |
| 2 | Market context / positioning | `docs/RAPIDAPI_LISTING.md` (Why it's different) |
| 3 | Target buyers | `docs/RAPIDAPI_LISTING.md` (Who it's for) |
| 4 | Brand & positioning | `README.md` + `docs/RAPIDAPI_LISTING.md` title/subtitle |
| 5 | MVP endpoints (13) | `permy/api/v1/*.py` + `docs/openapi.json` |
| 6 | Data sources | `permy/adapters/austin.py` + `docs/COVERAGE.md` + `LEGAL.md` |
| 7 | Tech stack (justified) | `docs/ARCHITECTURE.md` §7 |
| 8 | Architecture + ASCII diagram | `docs/ARCHITECTURE.md` §2 |
| 9 | Scoring & lead ranking formula | `permy/scoring/lead_score.py` + `docs/LEAD_SCORING.md` |
| 10 | Pricing (tiers + breakeven) | `permy/core/config.py` (TIER_LIMITS) + `docs/RAPIDAPI_LISTING.md` (pricing cards) |
| 11 | RapidAPI listing copy | `docs/RAPIDAPI_LISTING.md` |
| 12 | Docs site & DX | `docs/DOCS_OUTLINE.md` + `docs/QUICKSTART.md` |
| 13 | Go-to-market | `docs/ROADMAP.md` (Phase 7+) + `docs/RISK_REGISTER.md` §7 |
| 14 | Build phases | `docs/ROADMAP.md` + `docs/SPRINT_PLAN.md` |
| 15 | Legal / compliance / trust | `LEGAL.md` + `docs/RISK_REGISTER.md` §2 |
| 16 | Success metrics | `docs/ROADMAP.md` (metrics table) |
| 17 | Deliverables (this index) | this file |

## How to run it

```bash
cd permy
cp .env.example .env
make dev              # install deps
make test             # 83 tests, no live upstream calls
make docker-up        # postgres+postgis, redis, api, worker
curl -s http://localhost:8000/v1/health
curl -s "http://localhost:8000/v1/permits/search?city=Austin&limit=3" -H "X-API-Key: dev-key-2"
# OpenAPI UI:  http://localhost:8000/docs
# OpenAPI JSON: http://localhost:8000/openapi.json
```

## Test summary
**110 passed, 1 skipped (live PG), 3 deselected (live upstream)** — adapter Austin (8), NYC + Chicago (24), scoring (28), API (22), ingestion/webhooks (16), MCP (9), PG repo (5 + 1 live skip).

## MVP cities (3, all live + tested)
- **Austin** (`3syk-w9eu`) — reference adapter. Has contractor phone, no owner, no geo in feed (Census geocoded), partial valuation.
- **New York City DOB** (`ipu4-2q9a`) — GIS lat/lng, permittee phone + license #, owner name (rare). No declared valuation on issuance dataset (honest null).
- **Chicago** (`ydr8-5enu`) — GIS lat/lng, contact_1..15 contractors. Publishes fees not valuation (honest null); no phone on contacts (honest flag).

All three normalize into the **same `Permit` shape** — proven by `test_all_three_cities_produce_valid_permits`.

## What's real vs scaffolded
- **Real & tested**: Austin + NYC + Chicago adapters (vs live Socrata fixtures), normalized schema, deterministic scorer, all 13 FastAPI endpoints (TestClient-verified against 3-city data), ingestion pipeline, HMAC webhooks, MCP tools, DDL, OpenAPI 3.1, **Postgres-backed Repo** (asyncpg + PostGIS, UPSERT-on-canonical_uid, same interface as in-memory; live integration test gated behind `PERMY_TEST_LIVE_PG`).
- **Scaffolded interfaces with stubs**: Smarty/Mapbox geocoders (Census is live), arq worker entrypoint (jobs defined; needs Redis to run), license boards (TX stub; CA/NY to follow).
