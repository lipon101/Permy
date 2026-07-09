# Coverage — which cities, which fields, how fresh

> Permy is honest about coverage. If a city doesn't publish a field, we say so — and we flag it on every record (`dq_flags`) and in `enrichment.confidence`.

## Live now (9 cities, 2 portal types)

| City | State | Portal | Live? | Cadence | permits | valuation | contractor | owner | phone | geocode |
|---|---|---|---|---|---|---|---|---|---|---|
| Austin | TX | Socrata (`3syk-w9eu`) | ✅ | daily | ✅ | partial | ✅ | ❌ | ✅ | via Census |
| New York City | NY | DOB Socrata (`ipu4-2q9a`) | ✅ | daily | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ (GIS) |
| Chicago | IL | Socrata (`ydr8-5enu`) | ✅ | daily | ✅ | ❌ | ✅ | partial | ❌ | ✅ (GIS) |
| San Francisco | CA | Socrata / DataSF (`i98e-djp9`) | ✅ | daily | ✅ | ✅ (revised/est cost) | ❌ | ❌ | ❌ | ✅ (GeoJSON Point) |
| Seattle | WA | Socrata (`76t5-zqzr`) | ✅ | daily | ✅ | ✅ (estprojectcost) | ❌ | ❌ | ❌ | ✅ (lat/lng) |
| Los Angeles | CA | ArcGIS FeatureServer (layer 2) | ✅ | daily | ✅ | ✅ (VALUATION) | ❌ (CSLB join later) | ❌ | ❌ | ✅ (LAT/LON) |
| Miami-Dade | FL | ArcGIS MapServer (layer 1) | ✅ | daily | ✅ | ❌ (publishes fees) | ✅ (name + license #) | ❌ | ❌ | ✅ (reprojected StatePlane→WGS84) |

## Roadmap (weeks 5–12)
Dallas/Fort Worth · Phoenix (Accela — needs adapter) · Denver · Atlanta · Nashville · Orlando · Houston (aggregate-only, needs special handling) · San Diego · Boston.

## Field legend
- ✅ = published by the city, populated on most records.
- **partial** = published but frequently null (e.g. residential valuations in Austin).
- ❌ = not published by the city on permit records.

## Known gaps (honestly noted)
- **Austin** does not publish owner names on permits — we don't synthesize them.
- **NYC DOB** issuance dataset has no declared valuation (that's on the separate Job Application dataset) — honest null.
- **Chicago** publishes fees, not declared valuation; contacts have no phone — honest flags.
- **SF / Seattle** DBI/SDCI main permit records carry no contractor or owner — a license-board join (CA CSLB / WA L&I) is the Phase-2 enrichment path.
- **LA** LADBS FeatureServer has no contractor on the main feature; CA CSLB join planned.
- **Miami-Dade** publishes fees, not declared valuation; contractor name + license # but no phone; geometry is in a projected StatePlane CRS (reprojected to WGS84 via pyproj at ingest).
- **Houston** publishes only monthly aggregate counts (residential), not per-permit records — not currently supportable per-permit.
- **Dallas** Socrata endpoint froze in Aug 2020 — would be served as *archive* with `is_live=false`.

## Freshness
Every city row carries a `last_ingested_at` timestamp (see `/v1/coverage`). Most cities refresh daily; a few high-value cities move to near-real-time webhooks post-MVP. If a feed goes dark, the city flips to *archive* and we surface `last_ingested_at` so you know exactly how stale it is — we never serve stale data as if it were fresh.

## Request a city
Need a city we don't cover yet? Email cities@permy.dev — we prioritize by demand.
