# Permy — Architecture

> Developer-first municipal-intelligence infrastructure. This document is the source of truth for how data flows from a city's open-data portal to a paying developer's JSON response.

## 1. Design principles

1. **One normalized schema across all cities.** Every city adapter maps its dialect (Socrata SoQL, ArcGIS FeatureService, Accela, Tyler, CKAN, custom) into the same `Permit` model. Downstream code never branches on city.
2. **Provenance on every record.** `source_url`, `source_name`, `last_checked_at`, and a 0–1 `confidence` are non-optional. A buyer can always click through to the city's own page and judge how much to trust us.
3. **Deterministic scoring.** `lead_score` is a pure function of the permit + persona + market signal. No LLM in the hot path. Same inputs → same score, always auditable.
4. **Explicit `null`, never omission.** Missing fields are `null`, not absent. Schema stability is the contract that lets apps and agents rely on us across cities that publish different fields.
5. **Adapters are thin; the pipeline is shared.** A city adapter only does `fetch()` + `normalize()`. Geocoding, classification, license joins, scoring, and dedupe happen once, in the pipeline, for every city.
6. **Cheap to run.** Free-tier geocoder (Census), free open-data feeds, aggressive 24h caching, daily cron (not real-time for MVP). Unit economics work at $19/mo.

## 2. High-level data flow

```
                         ┌─────────────────────────────────────────────────────────────┐
                         │                       CRON (daily, per city)                │
                         │   Fly/Railway/Render timer  →  `permy-ingest <city-slug>`   │
                         └───────────────────────────────┬─────────────────────────────┘
                                                          │ enqueues
                                                          ▼
   ┌────────────┐    fetch()    ┌──────────────┐   normalize()   ┌──────────────────┐
   │  Austin    │ ◀────────────▶│   Adapter    │ ◀──────────────▶│  raw_permits     │  (RAW landing — verbatim JSONB)
   │  Socrata   │    HTTP/SoQL  │ (per city)   │                 │  + provenance    │
   ├────────────┤               ├──────────────┤                 └────────┬─────────┘
   │  NYC DOB   │               │  implements  │                          │
   ├────────────┤               │  CityAdapter │                          ▼
   │  Chicago   │               │  Protocol    │                   ┌──────────────────┐
   ├────────────┤               └──────┬───────┘                   │   pipeline:      │
   │  LADBS     │                      │                           │   geocode        │  (Census → Smarty on paid)
   ├────────────┤                      │                           │   classify       │  (keyword maps → optional LLM)
   │  Seattle   │                      │                           │   license join   │  (state boards)
   │  Miami-Dade│                      │                           │   score          │  (deterministic lead_score)
   │  ...       │                      │                           │   dedupe         │  (canonical_uid hash)
   └────────────┘                      │                           └────────┬─────────┘
                                        │                                    │ UPSERT on canonical_uid
                                        ▼                                    ▼
                                 ┌──────────────┐                  ┌──────────────────────────────────┐
                                 │ jurisdictions│                  │  SILVER (clean, normalized)      │
                                 │  + coverage  │                  │  permits │ contractors │        │
                                 │   (metadata) │                  │  properties │ markets           │
                                 └──────────────┘                  └──────────┬───────────────────────┘
                                                                                │
                                          ┌─────────────────────────────────────┼─────────────────────────────┐
                                          │                                     │                             │
                                          ▼                                     ▼                             ▼
                                  ┌──────────────┐                   ┌──────────────────┐              ┌──────────────┐
                                  │  FastAPI     │                   │  arq worker      │              │  S3 / R2     │
                                  │  /v1/* API   │                   │  webhook deliver │              │  CSV/JSON    │
                                  │  + OpenAPI   │                   │  (HMAC signed)   │              │  bulk export │
                                  │  + MCP server│                   └────────┬─────────┘              └──────────────┘
                                  └──────┬───────┘                            │ POST
                                         │                                    ▼
                ┌────────────────────────┼───────────────────┐      ┌──────────────────┐
                │                        │                   │      │  customer webhook│
                ▼                        ▼                   ▼      │  (verify sig)    │
        ┌──────────────┐         ┌──────────────┐    ┌──────────────┴──────────────────┘
        │ RapidAPI     │         │  Direct site  │    │
        │ marketplace  │         │  api.permy.dev│    │  alert matcher runs after each ingest:
        │ (SEO funnel) │         │  (Bearer)     │    │  new permits matching saved query → enqueue
        └──────────────┘         └───────────────┘    │  webhook.deliver job with backoff retries
```

## 3. Queue topology

Two job classes on one Redis-backed `arq` queue:

| Queue / job | Trigger | Work |
|---|---|---|
| `ingest_city` | cron per city (daily; near-real-time for a few high-value cities later) | fetch → normalize → geocode → classify → license join → score → dedupe → UPSERT |
| `deliver_webhook` | alert matcher finds new permits matching a saved query | POST signed HMAC payload to customer URL; retries 30s / 2m / 10m, then dead-letter |

A separate low-priority queue (`nightly_rollups`) recomputes `markets` (ZIP development scores) and contractor activity aggregates once per night so the hot read path is cheap.

## 4. Caching layer

- **Redis** is the rate-limit token bucket (per API key, per minute) and the `arq` queue backend.
- **Application cache** (Redis, 24h TTL): `GET /v1/permits/search` results keyed by normalized query hash. Permits update daily, so a 24h cache is safe and cuts DB load dramatically. `permits/{id}` and `properties/{id}/timeline` cached 1h. `markets/{zip}` cached until nightly recompute.
- **No cache** on `/health`, `/usage`, `/leads/ranked` (always fresh), or `/intelligence/score` (computed per call).

## 5. Per-city adapter interface

Every adapter implements this Protocol (`permy/adapters/base.py`). The pipeline is city-agnostic; adding a city = writing one adapter + registering it.

```python
class CityAdapter(Protocol):
    jurisdiction_slug: str   # 'austin-tx'
    city: str                # 'Austin'
    state: str               # 'TX'
    source_portal: str       # 'socrata' | 'arcgis' | 'accela' | 'tyler' | 'ckan' | 'custom'
    source_name: str         # human label

    def fetch(self, since: date | None = None, limit: int = 1000) -> list[dict]: ...
    def normalize(self, raw: dict) -> Permit: ...
    def source_meta(self) -> dict: ...   # coverage page metadata
```

Adding NYC DOB, for example, means: a `NYCDobAdapter` with `fetch()` hitting the DOB BIS/Socrata endpoint and `normalize()` mapping NYC's field names (`jobnum`, `jobtype`, `ownername`, …) into the same `Permit`. The pipeline, scoring, API, MCP server, and docs all keep working unchanged.

## 6. Table topology (Postgres + PostGIS)

Medallion layout. Raw landing preserves verbatim upstream JSONB for replay/audit; silver is the clean normalized layer; serving views denormalize for the API.

| Layer | Tables | Purpose |
|---|---|---|
| RAW | `raw_permits` | verbatim upstream record + provenance, never mutated |
| SILVER | `permits`, `contractors`, `properties`, `markets` | normalized, scored, deduped (`canonical_uid` UNIQUE) |
| OPS | `jurisdictions`, `alerts`, `webhook_deliveries`, `usage_daily` | metadata, saved searches, delivery audit, quota |
| SERVING | `v_permits_full` (view) | join permits↔contractors↔jurisdictions for the API |

Geo: `permits.geom` and `properties.geom` are `GEOGRAPHY(POINT,4326)` with GiST indexes for bbox queries. Full DDL in `permy/db/schema.sql`.

## 7. Why this stack (and where to swap)

| Choice | Why | When to swap |
|---|---|---|
| **Python 3.9 + FastAPI + Pydantic v2** | Fast to ship, OpenAPI 3.1 from code, great DX, async. Pydantic v2 gives the strict `extra="forbid"` + explicit-null contract we need. | If a second team is stronger in Node, Fastify is an equivalent. Don't run both. |
| **Postgres + PostGIS** | One DB for relational + geo + JSONB (raw payloads). PostGIS makes bbox + proximity queries trivial. | If you outgrow a single instance, Citus or a read-replica fan-out — but not before 25+ cities. |
| **Redis + arq** | One Redis for rate-limit + queue + cache. `arq` is async RQ — same worker process handles ingest + webhooks. | At very high webhook volume, split webhooks onto a dedicated queue/worker pool. |
| **Census geocoder (free)** | $0, no key, good enough for MVP. | Move to Smarty/Mapbox for rooftop accuracy on paid tiers (Pro+). |
| **Deterministic scoring (no LLM)** | Auditable, testable, cheap, deterministic. | Add a cheap-LLM pass (Haiku/mini) ONLY for `description_enriched` on top uncertain records — Phase 7+, behind a flag. |

## 8. Non-functional targets

- **p95 latency**: <400ms `/permits/search`, <250ms `/properties/{id}/timeline` (cached). Achieved via 24h query cache + GiST indexes + serving view.
- **Uptime**: 99.5% on paid tiers. Healthcheck on `/v1/health`; DB + Redis probes wired.
- **Freshness**: daily per city; `last_ingested_at` exposed on the coverage page so buyers know exactly how stale each city is.
- **Cost**: at MVP (10 cities, daily cron, Census geocoder, single small Postgres + Redis), infra is < $50/mo. Breakeven at ~3 Starter subscribers.

## 9. Failure modes & handling

- **Upstream feed goes dark** → adapter `fetch()` catches the error, marks `jurisdictions.is_live=false`, and the coverage page shows the city as *archive* with a `last_ingested_at` timestamp. We never serve stale data silently as if it were fresh.
- **Schema drift upstream** → `normalize()` is defensive: every field accessor goes through `_str/_int/_float/_date` helpers that return `None` on parse failure rather than crash. The record lands with `null`s + `dq_flags`.
- **Webhook endpoint down** → `deliver_webhook` retries 30s/2m/10m, then marks `webhook_deliveries.status='dead'` and surfaces it in a future `/v1/alerts` health field.
- **Rate-limit storm from a single key** → Redis token bucket returns 429 with `Retry-After`; no DB hit.
