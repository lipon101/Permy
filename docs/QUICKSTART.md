# Quickstart — Permy in 5 minutes

## 1. Get a key
Subscribe to the **Free** plan on RapidAPI. Your RapidAPI key is sent automatically in the `X-RapidAPI-Key` header on every request — you don't need to do anything else.

> Prefer the direct site? Use `https://api.permy.dev` and pass `Authorization: Bearer <key>`.

## 2. Your first call — roofing permits in Austin

```bash
curl -G "https://permy.p.rapidapi.com/v1/permits/search" \
  --data-urlencode "city=Austin" --data-urlencode "trade=roofing" --data-urlencode "limit=5" \
  -H "X-RapidAPI-Key: YOUR_KEY" -H "X-RapidAPI-Host: permy.p.rapidapi.com"
```

You'll get back normalized permits, each with an `enrichment` block:

```json
{
  "page": 1, "limit": 5, "total": 42,
  "permits": [{
    "id": "austin-tx:13725333",
    "canonical_uid": "5f3e9a1b8c0d4e6f7a8b9c0d",
    "jurisdiction_slug": "austin-tx",
    "source_url": "https://abc.austintexas.gov/web/permit/...",
    "source_name": "City of Austin — Building Permits",
    "address": {"street": "1011 Brickell Loop", "city": "Austin", "state": "TX", "zip": "78744", "full": "..."},
    "trade_category": "electrical",
    "work_class": "remodel",
    "valuation_usd": null,
    "dates": {"applied": "2026-06-22", "issued": "2026-07-08", "finaled": "2026-07-08", "expired": null},
    "current_status": "final",
    "contractor": {"name": "In Charge Electrical Services", "phone": "5127786240", "trade": "Electrical Contractor"},
    "enrichment": {
      "lead_score": 62,
      "recommended_action": "qualify",
      "reason": "[general] fresh signal=23/25, trade match=12/20 (trade=electrical, ~$—, issued=2026-07-08)",
      "dq_flags": ["valuation_unknown"],
      "confidence": 0.87
    }
  }]
}
```

Note: **missing fields are `null`, never omitted.** `source_url` and `confidence` are always present.

## 3. Ranked leads for your persona (Pro plan)

```python
import requests
r = requests.get("https://permy.p.rapidapi.com/v1/leads/ranked",
    headers={"X-RapidAPI-Key": "YOUR_KEY", "X-RapidAPI-Host": "permy.p.rapidapi.com"},
    params={"persona": "roofer", "city": "Austin", "limit": 10})
for lead in r.json()["leads"]:
    print(lead["lead_score"], lead["recommended_action"], lead["reason"])
```

Each lead has a `lead_score` (0–100), `recommended_action` (`call_now` / `qualify` / `monitor` / `skip`), and a human `reason` explaining the top factors. See [Concepts: Lead Scoring](./lead-scoring).

## 4. Your first webhook (Pro plan)

Create a saved search that fires when new roofing permits drop in Austin:

```javascript
import { Permy } from "permy-sdk";
const permy = new Permy("YOUR_KEY");

await permy.alerts.create({
  persona: "roofer",
  query: { city: "Austin", trade: "roofing" },
  webhook_url: "https://yourapp.com/permy-webhook",
});
```

Permy POSTs signed HMAC payloads to your URL within ~60s of new matching permits. Verify the signature:

```javascript
import crypto from "node:crypto";
const expected = crypto.createHmac("sha256", process.env.PERMY_WEBHOOK_SECRET)
  .update(req.rawBody).digest("hex");
if (expected !== req.headers["x-permy-signature"]) return res.status(401).send("bad sig");
// handle event
```

## 5. You're done 🎉

- **API Reference**: every endpoint, live in the playground → `/reference`
- **Which cities + fields**: → `/coverage`
- **How the score works**: → `/concepts/lead-scoring`
- **Agents**: install the MCP server → `/concepts/mcp`

> **One closed roofing, solar, or HVAC job pays for a year of Permy.**
