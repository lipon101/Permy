# Permy — Ops & Deployment Playbook

How to run Permy in production: host it (free-tier friendly), seed it, schedule
daily ingestion per city, keep it healthy, and list it on RapidAPI. Written for
a solo founder — every step is the cheapest option that still holds up to the
first paying users.

---

## 1. Free hosting options (pick one)

Permy is a stateless FastAPI app + an optional Postgres + an optional Redis
(worker only). You can run the **whole thing free** until you have real traffic.
Ranked by ease for a permit API:

### A. Render (recommended free start)
- **Web Service** (free): builds from the Dockerfile, sleeps after 15 min idle
  (fine for an API behind RapidAPI — the first request wakes it in ~30s).
- **Postgres** (free, 90 days then $7/mo): use it for the PG repo so data
  survives restarts and PostGIS bbox queries work. Until then the in-memory
  repo (seeded from fixtures) works for demos.
- **Cron Job** (free): one per city, `permy-ingest <slug> --since=$(date -d
  yesterday +%F)`, daily.
- Set `PERMY_ENV=prod`, `PERMY_API_KEYS=<generate>`, `PERMY_WEBHOOK_SECRET=<generate>`,
  `DATABASE_URL` = the Render PG internal URL.

### B. Fly.io (best free-tier DB)
- `fly launch` from the repo (detects the Dockerfile).
- `fly postgres create` (free 1GB, 256MB RAM — enough for MVP).
- `fly secrets set PERMY_ENV=prod PERMY_API_KEYS=... PERMY_WEBHOOK_SECRET=...`
- `fly scale vm free` (free tier: 3 shared-cpu 256MB VMs).
- Cron via `fly cron` or a cron-machine app: `permy-ingest <slug>` daily.
- **Worker** (webhooks): `fly scale worker free` running `permy-worker` — only
  needed once you have Pro-tier users with saved searches. Until then, skip it.

### C. Railway (free trial $5 credit, then usage-based)
- One-click Postgres + deploy from GitHub. Cheapest path to a always-on API
  if Render's sleep-on-idle bothers you. Cron via Railway's cron plugin.

### D. Koyeb / Northflank
- Both have always-on free nano containers. Good if you've used up Render/Fly
  free tiers. Koyeb builds from Dockerfile directly.

> **Cost ceiling for the first 90 days: $0.** Render free web + free PG (90d) +
> free cron. The only thing you pay for is a custom domain (~$10/yr from
> Cloudflare/Porkbun) — optional; `permy.onrender.com` works fine for RapidAPI.

---

## 2. First deploy (Render, ~10 minutes)

```bash
# 1. push to GitHub
git init && git add -A && git commit -m "Permy 9-city MVP" && git push

# 2. Render dashboard → New → Web Service → connect repo
#    - Build: Dockerfile (auto-detected)
#    - Plan: Free
#    - Env vars (set in dashboard):
PERMY_ENV=prod
PERMY_API_KEYS=<openssl rand -hex 24>     # your direct-site keys
PERMY_WEBHOOK_SECRET=<openssl rand -hex 32>
PERMY_BASE_URL=https://permy.onrender.com
#    (DATABASE_URL is auto-injected when you create the Render Postgres)

# 3. Create Postgres (New → PostgreSQL → Free) and link it to the web service.
#    Run the schema once (Render shell):
psql "$DATABASE_URL" -f permy/db/schema.sql

# 4. Seed from fixtures (Render shell) — gives the API real data immediately:
python -m permy.scripts.seed

# 5. Smoke it:
curl https://permy.onrender.com/v1/health
curl https://permy.onrender.com/v1/sample/coverage
curl -H "X-API-Key: <your-key>" https://permy.onrender.com/v1/coverage
```

---

## 3. Daily ingestion cron (per city)

One Render Cron Job per city (or one job looping all). The ingest CLI pulls the
last 2 days by default and UPSERTs into Postgres — re-running never duplicates.

```bash
# Render Cron Job → command:
permy-ingest austin-tx nyc-ny chicago-il sf-ca seattle-wa la-ca miami-fl
# schedule: 0 6 * * *  (daily 06:00 UTC — most cities publish overnight)
```

Or per-city for finer control / staggered rate-limit politeness:

| City        | Slug         | Suggested time (UTC) | Notes |
|-------------|--------------|----------------------|-------|
| Austin      | `austin-tx`  | 06:00 | Socrata, app token optional |
| NYC DOB     | `nyc-ny`     | 07:00 | Socrata, large dataset |
| Chicago     | `chicago-il` | 07:30 | Socrata |
| SF          | `sf-ca`      | 08:00 | Socrata (DataSF) |
| Seattle     | `seattle-wa` | 08:30 | Socrata |
| LA          | `la-ca`      | 09:00 | ArcGIS FeatureServer |
| Miami-Dade  | `miami-fl`   | 09:30 | ArcGIS MapServer |

The `--since=YYYY-MM-DD` flag overrides the 2-day rolling window when you
backfill (e.g. `permy-ingest austin-tx --since=2026-01-01`).

---

## 4. Adding a new city (checklist)

1. **Probe the feed** live (`curl`) and confirm it's Socrata or ArcGIS.
2. **Capture a fixture** `tests/fixtures/<city>/sample_3.json` (3 records, with
   geometry if the feed has it). This is your regression gold + offline dev data.
3. **Write the adapter**:
   - Socrata → copy `permy/adapters/sf.py`, swap resource id + field maps.
   - ArcGIS → subclass `permy/adapters/arcgis_base.py` (see `la.py`/`miami.py`).
4. **Register it** at module bottom (`register(MyAdapter())`).
5. **Add to `repo._CITY_FIXTURES`** in `permy/db/repo.py` and to the seed map in
   `permy/scripts/seed.py`.
6. **Write honest coverage flags** in `source_meta()` — `valuation`/`contractor`/
   `owner`/`phone`/`geocode` must reflect what the feed *actually* publishes.
7. **Tests**: normalize the 3 fixture records, assert the cross-city Permit
   shape, add to the N-city cross-source test.
8. **Deploy**: add the slug to the cron. Done.

---

## 5. Webhook worker (Pro-tier feature — add when first Pro user signs up)

Until you have Pro users with saved searches, you don't need the worker. When
you do:

```bash
# Render → New → Background Worker → same repo → start command:
permy-worker
# needs REDIS_URL (Render Key/Value, or Upstash free 10k cmds/day)
```

The worker (`permy.ingest.worker`) runs three arq jobs:
- `ingest_city` — cron-driven per-city ingestion
- `ingest_and_notify` — ingest + match new permits against active alerts +
  enqueue a signed webhook per match
- `deliver_webhook` — HMAC-SHA256 delivery with retries (30s, 2m, 10m, ×3)

Webhook signature: `HMAC-SHA256(body, PERMY_WEBHOOK_SECRET)` in
`X-Permy-Signature`; event type in `X-Permy-Event`. Receivers MUST verify.

---

## 6. Backups + cost ceiling

- **DB backups**: Render PG free has no managed backups. Run a daily cron:
  `pg_dump "$DATABASE_URL" | gzip > /tmp/permy-$(date +%F).sql.gz` → push to a
  free Cloudflare R2 bucket (10GB free). Or upgrade to Render PG Starter ($7/mo)
  for daily snapshots once you have paying users.
- **Cost ceiling**: stay on free tiers until ≥1 paying user. The break-even is
  one closed roofing/solar/HVAC job — that pays for a year of Pro.
- **Rate-limit politeness**: each adapter uses a 30s timeout + default limits
  (1000/call). Don't lower it; Socrata/ArcGIS anon limits are generous. Set
  `SOCRATA_APP_TOKEN` (free from data.austintexas.gov / data.sfgov.org) to raise
  the anon throttle for Austin/SF/NYC/Chicago/Seattle.

---

## 7. Health + monitoring

- `GET /v1/health` — public, returns `{status, db, redis, coverage_cities}`.
- Every response carries `X-Request-Id`; errors echo it in the envelope. Ask
  users to include it in support tickets.
- Structured JSON logs in prod (`PERMY_ENV=prod`) — pipe to Render log drain →
  a free Logtail/Seq instance for searchability.
- Set up a free UptimeRobot ping on `/v1/health` every 5 min (keeps Render's
  free tier warm too).

---

## 8. RapidAPI listing — go-live sequence

1. Deploy (section 2) so `https://permy.onrender.com/v1/health` is live.
2. Paste `docs/RAPIDAPI_LISTING.md` copy into the RapidAPI provider portal.
3. Point the provider **Base URL** at your deployed host
   (`https://permy.onrender.com`).
4. Wire pricing tiers to `PERMY_TIER_LIMITS` in `permy/core/config.py` (free
   100/day, starter 2k/mo, builder 10k/mo, pro 100k/mo, business 500k/mo).
5. Import `docs/openapi.json` into RapidAPI's endpoint editor (auto-generates
   the test console).
6. Publish. The sample-mode endpoints (`/v1/sample/*`, no key) are the funnel —
   prospects try from the RapidAPI console without subscribing, then convert.
