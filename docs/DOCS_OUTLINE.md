# Permy Docs — Site Outline

> Built with Mintlify (or Scalar). The OpenAPI 3.1 spec at `docs/openapi.json` drives the auto-generated API reference; the pages below are the hand-written conceptual + onboarding content.

## Landing page
`landing.html` is a self-contained, browseable marketing/docs landing page
(open directly in a browser — assets are bundled in `assets/`). It features the
hero mascot, all 13 endpoints, tabbed quickstart code, a real annotated permit
response, the lead-scoring formula, the intro video, and the 6 pricing cards.
A live-published version also exists as a webpage artifact.

## Top nav
`Overview` · `Quickstart` · `API Reference` · `Concepts` · `Coverage` · `Pricing` · `Changelog`

---

## Pages

### Overview
- What Permy is (1 paragraph + the one-line pitch)
- The normalized schema at a glance (a `Permit` annotated)
- Where data comes from (sources, freshness, provenance)
- 3 use-case cards: contractor leads, investor signals, agent integration

### Quickstart (< 5 minutes)
- Get a key (Free plan)
- First call (cURL) — roofing permits in Austin
- First ranked-leads call (Python)
- First webhook (Node) — create an alert + receive a signed delivery
- "You're done" + link to API Reference

### API Reference (auto-generated from OpenAPI 3.1)
- All 13 endpoints, grouped by tag:
  - **Permits**: `/permits/search`, `/permits/{id}`
  - **Properties**: `/properties/resolve`, `/properties/{id}/timeline`
  - **Contractors & Markets**: `/contractors/search`, `/contractors/{id}/activity`, `/markets/{zip}/development-score`
  - **Leads & Intelligence**: `/leads/ranked`, `/intelligence/score`
  - **Alerts & Webhooks**: `/alerts` (POST/GET/DELETE), `/webhooks/test`
  - **Meta**: `/coverage`, `/health`, `/usage`
- Interactive playground (try any endpoint with sample inputs; no key needed for sample mode)
- Schemas: Permit, Contractor, Property, MarketScore, RankedLead, IntelligenceResponse, ErrorResponse, …

### Concepts
- **The Normalized Schema** — one Permit shape across all cities; explicit `null` contract; `enrichment` block; provenance fields.
- **Lead Scoring** — the formula, weights, persona presets, bands → actions, the human `reason`. *(full draft below)*
- **Personas** — roofer / solar / hvac / investor / supplier / insurer / general; what each weights.
- **Webhooks** — HMAC signature verification, retry policy, event types, replay.
- **Rate Limits & Quotas** — per-tier limits, 429 handling, `Retry-After`.
- **Data Freshness & Provenance** — `last_ingested_at`, archive vs live, `confidence`.
- **Confidence Scores** — how source + freshness + completeness combine.
- **MCP / Agent Integration** — the 5 tools, stdio server, Claude/Cursor setup.

### Coverage
- Honest per-city table: city, portal, is_live, last_ingested_at, cadence, and which fields are published (permits / valuation / contractor / owner / phone / geocode) — each ✅/❌/partial.
- "Request a city" form.

### Pricing
- The 6 tiers (mirrors RapidAPI cards). One closed job pays for a year.

### Changelog
- Versioned release notes. v0.1 = Austin + scoring + webhooks + MCP.
