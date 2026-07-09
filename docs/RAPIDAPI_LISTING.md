# Permy — RapidAPI Listing Copy

> This is the actual copy to paste into the RapidAPI provider portal. SEO-optimized title, subtitle, full description, tags, code examples, and pricing cards.

---

## Title
`Permy — Building Permit & Construction Intelligence API`

## Subtitle
Normalized permits, contractor activity, property timelines, and ZIP development signals — ranked, sourced, and ready for your app.

## Short description (for card)
Give Permy an address, city, ZIP, contractor, or trade and get back clean, machine-readable municipal intelligence with source links and confidence scores.

---

## Full Description

### What it does
Permy is the friendly permit & construction-intelligence API. Send an address, city, ZIP, contractor name, or trade — get back normalized, ranked municipal intelligence: building permits, contractor activity, property timelines, and ZIP-level development signals. Every record is cross-city normalized, source-cited, confidence-scored, and ready for your app, agent, or pipeline.

### Key endpoints
- **`GET /v1/permits/search`** — search normalized permits by city, state, ZIP, trade, type, status, date range, valuation, contractor, keyword, or geo bbox.
- **`GET /v1/permits/{id}`** — full permit detail with enrichment + source links.
- **`GET /v1/properties/{id}/timeline`** — full permit history for an address.
- **`GET /v1/contractors/{id}/activity`** — permit count, trade mix, active cities, value bands, momentum.
- **`GET /v1/markets/{zip}/development-score`** — ZIP momentum + hotspot score 0–100.
- **`GET /v1/leads/ranked`** — ranked opportunities for a buyer persona with `lead_score` 0–100, `recommended_action`, and a human `reason`.
- **`POST /v1/intelligence/score`** — address/permit + persona → full intelligence bundle.
- **`POST /v1/alerts`** + signed **webhooks** — saved searches that fire on new matching permits.
- **`GET /v1/coverage`** — supported cities, fields per city, freshness.

### Who it's for
Roofing / solar / HVAC contractors & their agencies, real-estate investors & proptech apps, building-product suppliers, insurers & lenders, and developers building AI agents. **One closed roofing, solar, or HVAC job pays for a year of Permy.**

### Why it's different
- **Decision-scored outputs** — every permit carries a `lead_score` (0–100), `recommended_action` (call_now / qualify / monitor / skip), and a human `reason`. You don't just get data, you get a recommendation.
- **Source provenance + confidence on every record** — `source_url`, `source_name`, `last_checked_at`, and a 0–1 `confidence` so you always know where the data came from and how much to trust it.
- **Clean normalized cross-city schema** — one `Permit` shape whether the record came from Austin, NYC, or LA. Missing fields are explicit `null`, never omitted, so your app never breaks on schema drift.
- **Agent-ready** — ships an MCP server so Claude, Cursor, and other agents can call Permy directly.
- **Friendly, fast, self-serve** — copy-paste quickstart, interactive playground, honest coverage table.

### Data sources
Official city & county open-data portals (Socrata, ArcGIS Hub, Accela, Tyler, CKAN), state contractor license boards (CA CSLB, FL DBPR, NY DOL, WA L&I, TX TRCC, …), public county assessor records, Census/ACS demographics, and the free Census geocoder (Smarty/Mapbox rooftop geocoding on paid tiers). We use public records and official open-data APIs — never gated or ToS-protected sources. **Live now: 9 cities across two portal types** — Austin, NYC (DOB), Chicago, San Francisco, Seattle, Orlando (Socrata) + Los Angeles (LADBS), Miami-Dade, Fort Worth (ArcGIS). Every record carries source provenance + per-city field flags so you always know what's published vs. honestly null. Adding cities weekly.

### Getting started
1. **Try it free, no key needed** — call any `/v1/sample/*` endpoint right from the RapidAPI console (capped at 10 records, 30/day).
2. Subscribe to a plan (Free is fine to start — 100 requests/day).
3. Grab your RapidAPI key — it's sent automatically in the `X-RapidAPI-Key` header.
4. Call any endpoint. Example: find roofing permits in Austin:

```bash
curl -G "https://permy.p.rapidapi.com/v1/permits/search" \
  --data-urlencode "city=Austin" --data-urlencode "trade=roofing" --data-urlencode "limit=5" \
  -H "X-RapidAPI-Key: YOUR_KEY" -H "X-RapidAPI-Host: permy.p.rapidapi.com"
```

Official SDKs: **`permy-sdk`** (Python: `pip install permy-sdk`, Node: `npm install permy-sdk`) — typed wrappers over every endpoint with stable error codes. Full quickstart + interactive playground at **https://docs.permy.dev**.

---

## Tags (10)
`building permits` · `construction` · `contractor leads` · `roofing` · `solar` · `hvac` · `real estate` · `proptech` · `municipal data` · `webhooks`

## Categories
Data, Business, Real Estate, Developer Tools

---

## Code examples (5)

### cURL
```bash
# Ranked roofing leads in Austin
curl -G "https://permy.p.rapidapi.com/v1/leads/ranked" \
  --data-urlencode "persona=roofer" --data-urlencode "city=Austin" --data-urlencode "limit=10" \
  -H "X-RapidAPI-Key: YOUR_KEY" -H "X-RapidAPI-Host: permy.p.rapidapi.com"
```

### Python (requests)
```python
import requests

url = "https://permy.p.rapidapi.com/v1/permits/search"
headers = {"X-RapidAPI-Key": "YOUR_KEY", "X-RapidAPI-Host": "permy.p.rapidapi.com"}
params = {"city": "Austin", "trade": "roofing", "limit": 10, "sort": "lead_score"}

r = requests.get(url, headers=headers, params=params)
data = r.json()
for p in data["permits"]:
    print(p["address"]["full"], p["trade_category"],
          p["enrichment"]["lead_score"], p["enrichment"]["recommended_action"])
```

### JavaScript (fetch)
```javascript
const url = new URL("https://permy.p.rapidapi.com/v1/permits/search");
url.searchParams.set("city", "Austin");
url.searchParams.set("trade", "roofing");
url.searchParams.set("limit", "10");

const res = await fetch(url, {
  headers: { "X-RapidAPI-Key": "YOUR_KEY", "X-RapidAPI-Host": "permy.p.rapidapi.com" },
});
const { permits, total } = await res.json();
permits.forEach(p => console.log(p.address.full, p.enrichment.lead_score));
```

### PHP (cURL)
```php
<?php
$curl = curl_init();
curl_setopt_array($curl, [
  CURLOPT_URL => "https://permy.p.rapidapi.com/v1/permits/search?city=Austin&trade=roofing&limit=10",
  CURLOPT_RETURNTRANSFER => true,
  CURLOPT_HTTPHEADER => [
    "X-RapidAPI-Key: YOUR_KEY",
    "X-RapidAPI-Host: permy.p.rapidapi.com"
  ],
]);
$response = curl_exec($curl);
$data = json_decode($response, true);
foreach ($data["permits"] as $p) {
  echo $p["address"]["full"] . " — score " . $p["enrichment"]["lead_score"] . "\n";
}
curl_close($curl);
```

### Node SDK (permy-sdk — drop-in)
```javascript
import { Permy } from "permy-sdk"; // npm i permy-sdk
const permy = new Permy("YOUR_RAPIDAPI_KEY");

// What's being built in ZIP 78704?
const market = await permy.markets.developmentScore("78704");
console.log(market.hotspot_score, market.narrative);

// Top roofing leads, ranked
const { leads } = await permy.leads.ranked({ persona: "roofer", city: "Austin", limit: 10 });
leads.forEach(l => console.log(l.lead_score, l.recommended_action, l.reason));
```

---

## Pricing cards

### 🟢 Free — $0/mo
**100 requests/day · 1 saved search · no webhooks**
Perfect for kicking the tires and prototyping. SEO-friendly: your free calls help us both.
- `/permits/search` + `/permits/{id}`
- `/coverage`, `/health`, `/usage`
- 100 requests / day

### 🔵 Starter — $19/mo
**2,000 requests/mo · search + property timeline**
For a solo dev or small app exploring permit data.
- Everything in Free
- `/properties/resolve` + `/properties/{id}/timeline`
- 2,000 requests / month
- *One closed job pays for a year.*

### 🟣 Builder — $49/mo
**10,000 requests/mo · 5 saved searches · contractor lookup · CSV export**
For agencies and proptech apps in production.
- Everything in Starter
- `/contractors/search` + `/contractors/{id}/activity`
- 5 saved searches, CSV export
- 10,000 requests / month

### 🟠 Pro — $149/mo
**100,000 requests/mo · webhooks · ranked leads · intelligence/score · priority email**
The plan that pays for itself. Lead-gen agencies and serious contractors live here.
- Everything in Builder
- `/leads/ranked` + `/intelligence/score`
- Signed webhooks on new permits
- 100,000 requests / month, priority email support
- *Breakeven: one roofing/solar/HVAC job.*

### 🔴 Business — $499/mo
**500,000 requests/mo · bulk export · multiple API keys · 99.5% SLA · MCP server access**
For teams piping permits into their own pipelines and agents.
- Everything in Pro
- Bulk export, multiple API keys, 99.5% SLA
- MCP server access for Claude/Cursor/agents
- 500,000 requests / month

### ⚫ Enterprise — custom
**Snowflake/BigQuery delivery · white-label · dedicated infra · DPA**
- Volume pricing, dedicated infrastructure
- Data warehouse delivery (Snowflake / BigQuery)
- White-label, DPA, custom cities
- Talk to us: enterprise@permy.dev

> **Usage-based overage** available on Pro+ · **~17% annual discount** on all paid tiers.

---

## Listing FAQ (paste into RapidAPI FAQ section)

**How fresh is the data?**
Daily per city. `last_ingested_at` is exposed on `/v1/coverage` so you know exactly how stale each city is. A few high-value cities move to near-real-time webhooks post-MVP.

**Which cities are supported?**
Launching with Austin, NYC (DOB), and Chicago; adding LA, SF, Seattle, Miami-Dade, Dallas, Phoenix, Denver, Atlanta, Nashville weekly. See `/v1/coverage` for the live list and which fields each city publishes (valuation, contractor, owner, phone — honestly noted).

**Do you include contractor phone numbers?**
Where the city publishes them (Austin does — unusually generous). Where the city doesn't, we join against state license boards when possible. We never scrape gated sources.

**Is the data legal to use?**
Yes — only public records and official open-data APIs. Each record carries `source_url` so you can verify provenance. See our data license page for per-city terms.

**What's the lead_score?**
A deterministic 0–100 score blending recency, valuation, trade fit, property fit, contactability, and market momentum — persona-adjustable. ≥80 = call_now, 60–79 = qualify, 35–59 = monitor, <35 = skip. Full formula and weights are documented openly at https://docs.permy.dev/concepts/lead-scoring.

**Can agents call Permy?**
Yes — we ship an MCP server with 5 tools (search_permits, property_timeline, contractor_activity, zip_development_score, rank_leads) for Claude, Cursor, and other agents. Business tier and above.
