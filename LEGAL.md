# Legal

## Data sources
Permy uses **only public records and official open-data APIs**. We do not scrape gated or ToS-protected sources. Each adapter documents its source portal and the applicable license.

## Provenance
Every record carries `source_url`, `source_name`, and `last_checked_at`. A buyer can always click through to the city's own page and verify provenance. The `enrichment.confidence` field (0–1) reflects source trust, freshness, and field completeness.

## Personal data
- We use only what cities publish as public record. We do not sell personal data.
- Where a city's license restricts homeowner personal data, we omit or minimize it. Austin, for example, does not publish owner names on permits, and we do not synthesize them.
- Contractor contact information (phone, license) is published business data, not consumer PII.

## Privacy
- GDPR-aware. A Data Processing Agreement (DPA) is available on the Enterprise tier.
- No third-party sale of personal data.
- Data retention: raw landing records retained per upstream license; silver records updated/replaced on re-ingest.

## Upstream rate-limiting & caching
We rate-limit politely against upstream feeds (no aggressive parallelism) and cache aggressively (permits update daily, 24h cache is safe). This respects city infrastructure and keeps our costs low.

## "Data as of" / archive labeling
Each city carries a `last_ingested_at` and an `is_live` flag. Archive sources (frozen feeds) are clearly labeled and capped in `confidence`. We never serve stale data as if it were fresh.

## Code license
Apache-2.0 for the Permy codebase. Data is governed by each upstream city's open-data license; see per-record provenance.

## Trademark
"Permy" is a placeholder brand used consistently throughout. A USPTO search and domain acquisition (`permy.com`/`.io`/`.app`) are required before launch. Backup names: Permio, Permi.

## Disclaimer
Permy aggregates public records and provides derived signals (lead scores, market scores) for informational purposes. We do not guarantee the accuracy or completeness of upstream data. Buyers should verify critical decisions against the cited `source_url`.
