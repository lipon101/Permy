# Permy — Roadmap

## Phase 0 — Foundation (Week 1) ✅
Repo, FastAPI + Pydantic v2 + Postgres/PostGIS + Redis + arq, OpenAPI skeleton, auth + rate limiting, health/usage, CI.

## Phase 1 — 3 cities live (Weeks 2–3) 🚧
Austin + NYC + Chicago adapters end-to-end → normalized schema → `/permits/search` + `/permits/{id}` live with real data. *(Austin done in scaffold; NYC + Chicago next.)*

## Phase 2 — Enrichment (Week 4) 🚧
Geocoding (Census), trade classification, license-board join (TX + CA), `/contractors/search` + `/contractors/{id}/activity`, `/properties/resolve` + `/properties/{id}/timeline`.

## Phase 3 — Scoring & leads (Week 5) ✅ (module + tests done)
Deterministic `lead_score` + `/leads/ranked` + `/intelligence/score` + persona weights.

## Phase 4 — Markets & webhooks (Week 6) 🚧
`/markets/{zip}/development-score`, saved searches + signed HMAC webhooks, alert matcher, nightly rollups.

## Phase 5 — Docs & DX (Week 7) ✅ (copy drafted)
Mintlify/Scalar docs, interactive playground, coverage page, code examples, SDKs.

## Phase 6 — Launch (Week 8) ✅ (assets ready)
RapidAPI listing live, pricing tiers wired, free tier enforced, MCP server published.

## Phase 7+ — Ongoing
- Add cities weekly (→ 10 by month 3, → 25 by month 6).
- FEMA NFHL flood overlay → insurer risk enrichment.
- LLM `description_enriched` pass for uncertain records (behind flag).
- Bulk export + Snowflake/BigQuery delivery (Business/Enterprise).
- Near-real-time webhooks for a few high-value cities.
- Programmatic per-city content + comparison posts for organic distribution.

## Success metrics (targets)
| Metric | Target |
|---|---|
| Free → paid conversion | ≥ 3–5% |
| First paying user | within 60 days of RapidAPI listing |
| MRR | $1,000 within 6 months; $5,000 within 12 months |
| p95 latency | < 400ms search, < 250ms property timeline (cached) |
| Uptime (paid) | ≥ 99.5% |
| Cities, daily-fresh | ≥ 10 by month 3; ≥ 25 by month 6 |
| MCP integration partner | ≥ 1 by month 4 |
