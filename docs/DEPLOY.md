# Permy — RapidAPI Go-Live Checklist

The exact, ordered steps to get Permy **hosted free and listed on RapidAPI today**
so paying customers can subscribe and call it immediately. No demo, no sample
gaps — this is the real production path. ~30 minutes end to end.

---

## Step 1 — Generate your secrets (2 min)

```bash
# API key for the direct-site path (RapidAPI forwards its own keys automatically)
echo "PERMY_API_KEYS=$(openssl rand -hex 24)"
echo "PERMY_WEBHOOK_SECRET=$(openssl rand -hex 32)"
```
Save both — you'll paste them into your host's env config.

---

## Step 2 — Host it free (Render, ~10 min)

1. Push the repo to GitHub.
2. **Render → New → Web Service** → connect the repo.
   - **Build**: auto-detected from `Dockerfile`.
   - **Plan**: Free (sleeps after 15 min idle — fine behind RapidAPI; first request wakes it in ~30s).
   - **Environment**:
     ```
     PERMY_ENV=prod
     PERMY_API_KEYS=<from step 1>
     PERMY_WEBHOOK_SECRET=<from step 1>
     PERMY_BASE_URL=https://<your-service>.onrender.com
     ```
3. **New → PostgreSQL** (Free, 90 days) → link it to the web service. `DATABASE_URL` is auto-injected.
4. Open the web service **shell** and run once:
   ```bash
   psql "$DATABASE_URL" -f permy/db/schema.sql
   python -m permy.scripts.seed          # loads 27 real permits across 9 cities
   ```
5. **Smoke**:
   ```bash
   curl https://<your-service>.onrender.com/v1/health
   # → {"status":"ok","coverage_cities":9,...}
   curl https://<your-service>.onrender.com/v1/sample/coverage
   # → keyless; 9 cities
   curl -H "X-API-Key: <from step 1>" https://<your-service>.onrender.com/v1/coverage
   ```

> Prefer Fly.io? `fly deploy --remote-only` → `fly postgres create` → `fly secrets set ...` → `fly ssh console -C 'python -m permy.scripts.seed'`. See `docs/OPS.md`.

---

## Step 3 — Schedule daily ingestion (3 min)

**Render → New → Cron Job** (free), one job:
- **Command**: `permy-ingest austin-tx nyc-ny chicago-il sf-ca seattle-wa la-ca miami-fl orlando-fl fortworth-tx`
- **Schedule**: `0 6 * * *` (daily 06:00 UTC)

This pulls the last 2 days from each live city endpoint and UPSERTs into Postgres
(re-ingesting never duplicates — `canonical_uid` dedupe). Your data stays fresh
with zero ongoing work.

---

## Step 4 — List on RapidAPI (10 min)

1. Go to **rapidapi.com** → **Provider** → **Add API**.
2. Fill from `docs/RAPIDAPI_LISTING.md`:
   - **API name**: `Permy — Building Permit & Construction Intelligence API`
   - **Short description**: the subtitle from the listing doc.
   - **Long description**: the 6-section description.
   - **Tags**: building permits, construction, contractor leads, roofing, solar, hvac, real estate, proptech, municipal data, webhooks.
3. **Endpoints → Import OpenAPI**: upload `docs/openapi.json`. RapidAPI auto-generates the test console for all 20 endpoints.
4. **Base URL**: `https://<your-service>.onrender.com`
5. **Pricing**: create the 5 tiers matching `permy/core/config.py` `TIER_LIMITS`:
   - Free $0 — 100/day
   - Starter $19 — 2,000/mo
   - Builder $49 — 10,000/mo
   - Pro $149 — 100,000/mo (webhooks + leads + intelligence)
   - Business $499 — 500,000/mo (MCP + bulk + SLA)
6. **Publish.**

> RapidAPI forwards the subscriber's key in `X-RapidAPI-Key`; Permy reads it as `X-API-Key` (the auth middleware checks both — see `permy/middleware/auth.py`). Unknown keys default to the `free` tier so new subscribers work instantly.

---

## Step 5 — Publish the docs + playground (3 min)

- `docs/landing.html` is your marketing site + interactive playground (the playground calls `/v1/sample/*` keyless — no signup to try).
- `docs/dashboard.html` is the coverage + endpoint dashboard.
- Host both on **Cloudflare Pages** or **Netlify** (free): connect the repo, build command none, output dir `docs`. Or just upload the two HTML files.
- Point the playground at your live API by default (it already uses `https://permy.onrender.com`; override per-visitor with `?api=...`).

---

## Step 6 — (Optional, when first Pro user signs up) Webhook worker

Pro-tier saved searches need the arq worker for real HMAC webhook delivery:
- **Render → New → Background Worker** → same repo → start command `permy-worker`.
- Add **Render Key/Value** (Redis, free) → set `REDIS_URL`.
- The worker matches new permits against active alerts and delivers signed webhooks with retries (30s / 2m / 10m × 3).

Skip this until you have a Pro subscriber — the API + cron work standalone until then.

---

## Verification — it's really live

```bash
# 1. health (public)
curl https://<host>/v1/health
# 2. sample mode (no key — the funnel)
curl https://<host>/v1/sample/permits/search?city=Austin
# 3. real endpoint (key required)
curl -H "X-API-Key: <key>" https://<host>/v1/leads/ranked?persona=roofer
# 4. 9 cities in coverage
curl -H "X-API-Key: <key>" https://<host>/v1/coverage | python -m json.tool
# 5. unknown route → 404 (no auth leak)
curl -i https://<host>/v1/totally/fake
# 6. security headers present
curl -sI https://<host>/v1/health | grep -i 'x-content-type-options\|strict-transport'
```

All six green = production-ready and sellable. The first paying roofing/solar/HVAC
contractor who closes one job pays for a year of any tier.
