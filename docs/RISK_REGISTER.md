# Permy — Risk Register

> Risks that could kill or wound the product, ordered by severity × likelihood. Each has a concrete mitigation and an owner.

## 1. Data-source fragility (SEVERITY high × LIKELIHOOD high)

**Risk:** Upstream open-data feeds change schema, go dark, rate-limit us, or get deprecated (e.g. Dallas' Socrata endpoint froze in Aug 2020; Phoenix/Tampa block public catalog API access with 403; Atlanta/Nashville/Denver don't expose Socrata at all).

**Mitigations:**
- **Defensive `normalize()`** — every field accessor goes through `_str/_int/_float/_date` helpers that return `None` on parse failure, never crash. Schema drift produces `null`s + `dq_flags`, not outages.
- **Provenance + liveness flag** — `jurisdictions.is_live` flips to false when a feed fails; the coverage page shows the city as *archive* with `last_ingested_at`. We never serve stale data silently as fresh.
- **Raw landing table** — `raw_permits` keeps verbatim upstream JSONB so we can replay/re-derive if a feed's schema changes.
- **ArcGIS/Accela adapters** for cities without Socrata (different query model, but a real path — see `docs/ARCHITECTURE.md` §5).
- **Daily health probe** per city; alert on 3 consecutive failures.
- **Never depend on one city** — the model is multi-city from day 1; losing one city degrades coverage, not the product.

**Owner:** data/infra engineer.

## 2. Legal / compliance (SEVERITY high × LIKELIHOOD medium)

**Risk:** Misusing public records (homeowner PII), violating a city's open-data license, or operating in a way that looks like scraping gated/ToS-protected sources.

**Mitigations:**
- **Public records + official APIs only.** No scraping gated portals. Each adapter documents its source portal and license.
- **Provenance on every record** (`source_url`, `source_name`, `last_checked_at`) — auditable chain of custody.
- **Omit/minimize homeowner personal data** where a city's license restricts it; Austin doesn't publish owner names on permits, and we don't synthesize them.
- **Per-city license review** before going live in a new city (part of the adapter checklist).
- **GDPR-aware**: no selling of personal data; DPA available on Enterprise; data retention policy documented.
- **Clear "data as of" timestamps**; archive vs live clearly labeled.

**Owner:** founder + counsel (review per new city).

## 3. Competitive (SEVERITY medium × LIKELIHOOD high)

**Risk:** Incumbents (PermitStack, Shovels, PermitRadar, PermitCore, ATTOM/Cotality, Construction Monitor) or Apify scrapers undercut or out-feature us.

**Mitigations:**
- **Differentiate, don't clone.** Permy's wedge is *developer-first, decision-scored, source-cited, normalized, agent-ready* — not another dashboard. PermitStack is a SaaS dashboard; Shovels is a warehouse; Apify actors are raw scrapers without scoring/normalization. We sit in a different cell of the market.
- **Friendliness + speed-to-value.** Copy-paste quickstart, honest coverage, MCP server. Incumbents are corporate; we're the helpful permit buddy.
- **Price under enterprise.** $19–$499 self-serve vs ATTOM/Cotality enterprise sales. One job pays for a year.
- **Distribution moat: RapidAPI SEO + MCP registry + programmatic per-city content.** Low CAC, compounding.
- **Ship faster than they can clone us.** Lead scoring + personas + webhooks + MCP in 4 weeks; keep adding cities weekly.

**Owner:** founder.

## 4. Cost / unit economics (SEVERITY medium × LIKELIHOOD medium)

**Risk:** Geocoding, DB, or LLM costs exceed revenue at low tiers; a free-tier abuser spikes the bill.

**Mitigations:**
- **Free geocoder (Census) for MVP**; Smarty/Mapbox only on paid tiers, and only for rooftop accuracy.
- **No LLM in the hot path** — deterministic scoring. LLM enrichment (Phase 7+) is a cheap Haiku/mini pass on *uncertain records only*, behind a flag.
- **24h query cache** (Redis) — permits update daily, so caching is safe and cuts DB load hard.
- **Free tier capped at 100/day + 1 saved search, no webhooks.** Token-bucket rate limit + daily quota in `usage_daily`.
- **Infra < $50/mo at MVP** (single small Postgres + Redis + daily cron on Fly/Railway). Breakeven at ~3 Starter subs.

**Owner:** data/infra engineer.

## 5. Data quality / coverage gaps (SEVERITY medium × LIKELIHOOD high)

**Risk:** Cities publish uneven fields (Austin has phone; Orlando doesn't; Houston only monthly aggregates; residential valuations often null). Buyers lose trust if gaps are hidden.

**Mitigations:**
- **Honest coverage table** — `/v1/coverage` and the docs show exactly which fields each city publishes (✅/❌/partial). Never overpromise.
- **Explicit `null` + `dq_flags`** — missing fields are flagged (`valuation_unknown`, `no_phone`, `trade_unclassified`) so the buyer's app can decide, not guess.
- **Confidence score** on every record — source + freshness + completeness → 0–1. Surface as "verified" vs "unverified" in buyer UIs.
- **License-board joins** backfill contractor phone/status where the permit feed lacks it (best-effort).
- **Pick launch cities with rich feeds** (Austin, NYC DOB, Chicago) — prove value before tackling thin-feed cities.

**Owner:** data engineer.

## 6. Freshness / latency (SEVERITY medium × LIKELIHOOD medium)

**Risk:** Daily cron feels stale to lead-gen buyers who want same-day roofing permits; API latency exceeds the <400ms p95 target as data grows.

**Mitigations:**
- **Near-real-time webhooks for a few high-value cities** post-MVP (Phase 7+) — poll the feed every 15–60min for those, daily for the rest.
- **`last_ingested_at` exposed** so buyers know exactly how fresh each city is — manage expectations honestly.
- **24h cache + GiST indexes + serving view** hold p95 under target; nightly rollups keep market reads cheap.
- **Read replicas** before sharding — not needed before 25+ cities.

**Owner:** data/infra engineer.

## 7. RapidAPI discovery / distribution (SEVERITY medium × LIKELIHOOD medium)

**Risk:** The RapidAPI listing doesn't get enough organic traffic; the marketplace is crowded.

**Mitigations:**
- **The listing IS the funnel** — invest in SEO title/subtitle/tags/description (done in `docs/RAPIDAPI_LISTING.md`).
- **MCP registry listings** (Smithery, Glama, Claude tools) — agent adoption is a 2026 distribution channel incumbents aren't on yet.
- **Programmatic per-city content** ("Building permits in Austin", "Top roofing contractors in Austin") that ranks and links into the API.
- **Honest comparison posts** (PermitStack vs Permy, etc.) — useful, not hit pieces.
- **No paid ads / cold outbound for MVP** — optimize for self-serve.

**Owner:** founder.

## 8. Trademark / naming (SEVERITY low × LIKELIHOOD low — but high blast radius)

**Risk:** "Permy" is trademarked or `permy.com` is taken/expensive.

**Mitigations:**
- **USPTO search + .com/.io/.app availability check before launch** (Sprint 4, S4-8).
- **Swappable name** — "Permy" is a placeholder used consistently; a rename is a global find-replace. Backups ready: Permio, Permi.

**Owner:** founder.

## 9. Single-founder / bus factor (SEVERITY high × LIKELIHOOD low)

**Risk:** MVP is a small team; losing the data engineer stalls city expansion.

**Mitigations:**
- **Thin adapters behind one Protocol** — onboarding a new city is a single self-contained file; a contractor can ship one in a day.
- **Recorded fixtures + tests** mean the pipeline is regression-safe without tribal knowledge.
- **Docs are the source of truth** — architecture, adapter interface, scoring formula, sprint plan all written down.

**Owner:** founder.
