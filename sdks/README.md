# Permy SDKs

Official SDKs for the **Permy — Building Permit & Construction Intelligence API**.

Both SDKs are thin, typed wrappers over the `/v1` REST endpoints. They work
against the RapidAPI gateway (`https://permy.p.rapidapi.com`), the direct site
(`https://api.permy.dev`), or a local instance (`http://localhost:8000`).

## Python

```bash
pip install permy-sdk
```

```python
from permy_sdk import Permy, PermyError

p = Permy(api_key="YOUR_RAPIDAPI_KEY", base_url="https://permy.p.rapidapi.com")

# sample mode — no key needed, great for kicking the tires
print(p.sample_coverage())

# real endpoints
permits = p.search_permits(city="Austin", trade="roofing", limit=25)
lead = p.get_permit("austin-tx:12345")
cov = p.coverage()

# Pro+ features
leads = p.rank_leads(persona="roofer", limit=10)
intel = p.score_intelligence(address="10912 Mystic Timber Dr, Austin, TX 78754", persona="roofer")
alert = p.create_alert(persona="roofer", query={"city": "Austin", "trade": "roofing"},
                       webhook_url="https://your.app/permy-webhook")

# error handling — every non-2xx raises PermyError with a stable code
try:
    p.search_permits(limit=99999)
except PermyError as e:
    print(e.code, e.status)  # e.g. "quota_exceeded" 429
```

## Node / TypeScript

```bash
npm install permy-sdk
```

```typescript
import { Permy, PermyError } from "permy-sdk";

const p = new Permy({ apiKey: "YOUR_RAPIDAPI_KEY", baseUrl: "https://permy.p.rapidapi.com" });

// sample mode — no key needed
console.log(await p.sampleCoverage());

// real endpoints
const permits = await p.searchPermits({ city: "Austin", trade: "roofing", limit: 25 });
const lead = await p.getPermit("austin-tx:12345");
const cov = await p.coverage();

// Pro+ features
const leads = await p.rankLeads("roofer", { limit: 10 });
const intel = await p.scoreIntelligence({ address: "10912 Mystic Timber Dr, Austin, TX 78754", persona: "roofer" });
const alert = await p.createAlert({ persona: "roofer", query: { city: "Austin", trade: "roofing" }, webhook_url: "https://your.app/permy-webhook" });

// error handling — every non-2xx throws PermyError with a stable code
try {
  await p.searchPermits({ limit: 99999 });
} catch (e) {
  if (e instanceof PermyError) console.log(e.code, e.status); // e.g. "quota_exceeded" 429
}
```

## Stable error codes

Every error response uses the unified envelope `{error: {code, message, ...}}`.
The SDKs surface `code` directly so you can branch:

| code | HTTP | meaning |
|------|------|---------|
| `missing_api_key` | 401 | no `X-API-Key` provided |
| `rate_limited` | 429 | per-minute rate limit hit |
| `quota_exceeded` | 429 | daily/monthly quota (or sample 30/day) hit |
| `feature_not_available` | 403 | endpoint needs a higher tier |
| `not_found` | 404 | permit / property / route not found |
| `validation_error` | 422 | bad query params |
| `internal_error` | 500 | server error (include `request_id` in support tickets) |

## Webhook signature verification

When an alert fires, Permy POSTs a signed HMAC-SHA256 payload to your
`webhook_url`. Verify it (Python example):

```python
import hmac, hashlib
expected = hmac.new(SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
hmac.compare_digest(expected, request.headers["X-Permy-Signature"])
```

The event type is in `X-Permy-Event` (currently `permit.new`).
