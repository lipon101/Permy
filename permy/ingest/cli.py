from __future__ import annotations

"""Ingestion CLI — ``permy-ingest`` runs an incremental pull for configured cities.

Pulls LIVE data from each city's open-data endpoint, runs it through the pipeline
(normalize -> geocode -> classify -> score), and PERSISTS the results to the
configured repo (Postgres in prod via UPSERT, in-memory in dev). Re-ingesting
updates records in place — never duplicates — thanks to canonical_uid dedupe.

Usage:
    permy-ingest                       # all cities, rolling 2-day window
    permy-ingest austin-tx             # one city
    permy-ingest austin-tx nyc-ny      # a few cities
    permy-ingest --since=2026-07-01 sf-ca   # explicit start date

Exits 0 on success (even if some cities failed — partial progress is reported),
1 if nothing could be processed at all. Per-city failures are printed but don't
abort the batch.
"""
import sys  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from typing import List, Optional, Tuple  # noqa: E402

from permy.adapters.base import ADAPTERS  # noqa: E402
from permy.db.repo import Repo, get_repo  # noqa: E402
from permy.ingest.pipeline import process_record  # noqa: E402


def _parse_args(argv: List[str]) -> Tuple[List[str], Optional[date]]:
    """Split argv into (cities, since). Supports --since=YYYY-MM-DD anywhere."""
    cities: List[str] = []
    since: Optional[date] = None
    for a in argv:
        if a.startswith("--since="):
            try:
                since = date.fromisoformat(a.split("=", 1)[1])
            except ValueError:
                print(f"  invalid --since date: {a} (use YYYY-MM-DD)")
                sys.exit(2)
        elif a.startswith("--"):
            continue  # ignore unknown flags gracefully
        else:
            cities.append(a)
    return cities, since


def _persist(repo: Repo, permit) -> bool:
    """Insert-or-update a permit into the repo. Returns True if newly added.

    The in-memory repo dedupes by canonical_uid (replace in place); the PG repo
    UPSERTs on conflict via its own upsert_permit method.
    """
    if hasattr(repo, "permits"):
        for i, existing in enumerate(repo.permits):
            if existing.canonical_uid == permit.canonical_uid:
                repo.permits[i] = permit
                return False
        repo.permits.append(permit)
        # keep secondary indexes fresh for the in-memory repo
        if hasattr(repo, "_index_contractor"):
            repo._index_contractor(permit)
        if hasattr(repo, "_index_property"):
            repo._index_property(permit)
        if hasattr(repo, "_recompute_markets"):
            repo._recompute_markets()
        return True
    if hasattr(repo, "upsert_permit"):  # PG repo
        return bool(repo.upsert_permit(permit))
    return False


def run() -> None:
    argv = [a for a in sys.argv[1:] if a != "-m" and not a.endswith(".py")]
    cities, since = _parse_args(argv)
    if not cities:
        cities = list(ADAPTERS.keys())
    if not cities:
        print("No adapters registered. Add a city adapter first.")
        sys.exit(1)
    if since is None:
        since = date.today() - timedelta(days=2)  # rolling 2-day window for safety

    repo = get_repo()
    total_processed = 0
    total_added = 0
    failures = 0
    summary = {}
    for slug in cities:
        if slug not in ADAPTERS:
            print(f"  unknown city '{slug}' (registered: {sorted(ADAPTERS.keys())})")
            failures += 1
            continue
        adapter = ADAPTERS[slug]
        try:
            raws = adapter.fetch(since=since, limit=2000)
            added = 0
            processed = 0
            for raw in raws:
                p = process_record(raw, adapter)
                is_new = _persist(repo, p)
                added += 1 if is_new else 0
                processed += 1
            total_processed += processed
            total_added += added
            summary[slug] = {"fetched": len(raws), "processed": processed, "added": added}
            print(f"  {slug}: fetched={len(raws)} processed={processed} added={added}")
        except Exception as e:  # noqa: BLE001 — one city failing shouldn't abort the batch
            failures += 1
            print(f"  {slug}: {type(e).__name__}: {e}")
            summary[slug] = {"error": str(e)}

    print("ingest complete:", summary)
    print(f"  totals: processed={total_processed} added={total_added} failures={failures}")
    if total_processed == 0 and failures == len(cities):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    run()
