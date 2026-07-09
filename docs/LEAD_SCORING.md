# Concepts — Lead Scoring

> Permy's `lead_score` is a **deterministic, persona-adjustable** 0–100 score attached to every permit. It's the core differentiator: you don't just get data, you get a recommendation.

## The formula

`lead_score` is a weighted sum of six components. Each component is scored 0–1, then multiplied by its weight (which sums to 100), giving a 0–100 integer.

| Component | Max weight | What it measures |
|---|---|---|
| **recency** | 25 | How fresh the permit signal is (issued/applied/finaled date). Full strength ≤7 days; decays to 0 at 180 days. |
| **valuation** | 25 | Declared job value, log-scaled. unknown=0.3, $5k≈0.4, $25k≈0.55, $100k≈0.7, $500k≈0.85, $5M+=1.0. |
| **trade_fit** | 20 | Match between the permit's trade and the persona's target trades. 1.0 exact, 0.5 adjacent (building/general), 0.25 unknown. |
| **property_fit** | 10 | Property characteristics the persona cares about (e.g. roofer/solar like alterations of existing homes; investors like multi-family; suppliers like new builds). |
| **contactability** | 10 | Can the buyer actually reach someone? Phone +0.6, license +0.2, name +0.1, owner +0.1. |
| **market_momentum** | 10 | ZIP `hotspot_score` (0–100) → 0–1. |

```
lead_score = round(
    recency       * w_recency
  + valuation     * w_valuation
  + trade_fit     * w_trade_fit
  + property_fit  * w_property_fit
  + contactability* w_contactability
  + momentum      * w_momentum
)
```

## Bands → recommended_action

| Score | Action | Meaning |
|---|---|---|
| ≥ 80 | `call_now` | Hot — contact today. |
| 60–79 | `qualify` | Strong — qualify then contact. |
| 35–59 | `monitor` | Watch — add to a nurture list. |
| < 35 | `skip` | Low — ignore. |

## Persona weight presets (default, opinionated)

Weights always sum to 100, but the distribution shifts by persona. These are the defaults; pass `weights` to `/v1/leads/ranked` to override per call.

| Persona | recency | valuation | trade_fit | property_fit | contactability | momentum |
|---|---|---|---|---|---|---|
| **roofer** | 30 | 15 | 25 | 10 | 10 | 10 |
| **solar** | 25 | 15 | 25 | 15 | 10 | 10 |
| **hvac** | 28 | 17 | 22 | 10 | 13 | 10 |
| **investor** | 10 | 30 | 10 | 20 | 5 | 25 |
| **supplier** | 15 | 25 | 15 | 5 | 10 | 30 |
| **insurer** | 12 | 15 | 20 | 25 | 8 | 20 |
| **general** | 25 | 25 | 20 | 10 | 10 | 10 |

**Why these?** A roofer cares most about freshness (permits cool fast) and trade fit. An investor cares about value + multi-family + ZIP momentum. A supplier cares about commercial volume + market heat (materials demand). An insurer weighs property fit and risk-relevant trades.

## Target trades per persona

| Persona | Target trades |
|---|---|
| roofer | roofing |
| solar | solar, electrical |
| hvac | hvac |
| investor | building, general |
| supplier | building, general, roofing, hvac |
| insurer | roofing, electrical, plumbing, hvac |
| general | roofing, solar, hvac, building, general |

## The human `reason`

Every scored permit includes a `reason` string explaining the top 2–3 contributing factors, the persona, key facts (trade, value, issued date), and any data-quality warnings. Example:

```
[roofer] fresh signal=23/30, trade match=25/25, contactability=6/10 (trade=roofing, ~$45,000, issued=2026-07-08) ⚠ valuation_unknown
```

This is what makes Permy "friendly" — the API doesn't just hand you a number, it tells you *why*, in plain English, ready to surface in your own UI.

## Data-quality flags (`dq_flags`)

Sparse records are flagged honestly so your app can decide how to handle them:

| Flag | Meaning |
|---|---|
| `valuation_unknown` | City didn't publish a job value (common on residential). |
| `trade_unclassified` | Trade couldn't be inferred from description/fields. |
| `no_contractor` | No contractor on the record. |
| `no_phone` | Contractor present but no phone published. |
| `weak_geocode` | Geocode confidence < 0.6. |

## Confidence (separate from lead_score)

`enrichment.confidence` (0–1) is **not** a lead quality score — it's a **data trust** score blending source trust (official feed vs archive), freshness (how recently we verified the record), and field completeness. Use it to decide whether to show a record prominently or annotate it as "verified" vs "unverified" in your UI.

## Determinism is a feature

The scorer is pure: no I/O, no LLM, no randomness. **Same inputs → same score, always.** That makes it auditable, testable, and explainable to a skeptical buyer. A cheap-LLM refinement pass for `description_enriched` on the most uncertain records is a Phase 7+ enhancement, kept behind a flag — the deterministic score itself never depends on an LLM.

## Overriding weights

Pass a custom `weights` object to `/v1/leads/ranked` (weights must sum to 100). Example — a roofer who only cares about fresh, contactable leads:

```json
{ "persona": "roofer", "weights": {
    "recency": 45, "valuation": 0, "trade_fit": 20, "property_fit": 0,
    "contactability": 25, "market_momentum": 10 } }
```

## See also
- [The Normalized Schema](./normalized-schema) — what every `Permit` contains.
- [Confidence Scores](./confidence) — the trust score, in depth.
- [API Reference: /leads/ranked](/reference#leads-ranked)
