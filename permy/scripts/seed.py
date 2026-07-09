from __future__ import annotations

"""``permy-seed`` — first-run seeding from recorded fixtures.

Loads each city's recorded fixture (tests/fixtures/<city>/sample_3.json) into the
configured repo (Postgres in prod, in-memory in dev/test) so the API has real
data to serve immediately after deploy. Idempotent: re-running never duplicates
(records are deduped by canonical_uid, and the PG repo UPSERTs on conflict).

Usage:
    python -m permy.scripts.seed           # seed all 7 cities
    python -m permy.scripts.seed austin    # seed one city (by slug prefix)
    python -m permy.scripts.seed sf miami  # seed a few

City args match by slug prefix: "austin" → austin-tx, "nyc" → nyc-ny, etc.
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional

from permy.db.repo import get_repo

# (arg prefix, adapter module path, adapter class, fixture subdir)
_CITIES = (
    ("austin", "permy.adapters.austin", "AustinAdapter", "austin"),
    ("nyc", "permy.adapters.nyc", "NYCAdapter", "nyc"),
    ("newyork", "permy.adapters.nyc", "NYCAdapter", "nyc"),
    ("chicago", "permy.adapters.chicago", "ChicagoAdapter", "chicago"),
    ("sf", "permy.adapters.sf", "SFAdapter", "sf"),
    ("sanfrancisco", "permy.adapters.sf", "SFAdapter", "sf"),
    ("seattle", "permy.adapters.seattle", "SeattleAdapter", "seattle"),
    ("la", "permy.adapters.la", "LAAdapter", "la"),
    ("losangeles", "permy.adapters.la", "LAAdapter", "la"),
    ("miami", "permy.adapters.miami", "MiamiAdapter", "miami"),
    ("orlando", "permy.adapters.orlando", "OrlandoAdapter", "orlando"),
    ("fortworth", "permy.adapters.fortworth", "FortWorthAdapter", "fortworth"),
    ("fort", "permy.adapters.fortworth", "FortWorthAdapter", "fortworth"),
)


def _fixtures_root() -> Path:
    # permy/scripts/seed.py → permy/scripts → permy → repo root → tests/fixtures
    return Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"


def _resolve_cities(args: List[str]) -> List[Dict[str, str]]:
    if not args:
        # default: every city (dedupe by fixture subdir)
        seen = set()
        out = []
        for prefix, mod, cls, sub in _CITIES:
            if sub not in seen:
                seen.add(sub)
                out.append({"prefix": prefix, "module": mod, "cls": cls, "subdir": sub})
        return out
    wanted = {a.lower().replace("-", "").replace("_", "") for a in args}
    out = []
    for prefix, mod, cls, sub in _CITIES:
        if prefix in wanted:
            out.append({"prefix": prefix, "module": mod, "cls": cls, "subdir": sub})
    return out


def run() -> None:
    import importlib

    args = sys.argv[1:]
    cities = _resolve_cities(args)
    if not cities:
        print(f"No matching cities. Known prefixes: {sorted({c[0] for c in _CITIES})}")
        sys.exit(1)

    repo = get_repo()
    root = _fixtures_root()
    total_before = len(getattr(repo, "permits", []))
    total_added = 0
    for c in cities:
        fx = root / c["subdir"] / "sample_3.json"
        if not fx.exists():
            print(f"  ✗ {c['subdir']}: no fixture at {fx}")
            continue
        mod = importlib.import_module(c["module"])
        adapter_cls = getattr(mod, c["cls"])
        adapter = adapter_cls()
        try:
            added = repo.seed_from_fixture(adapter, fx)
            total_added += added
            print(f"  ✓ {c['subdir']}: +{added} records (total now {len(getattr(repo, 'permits', []))})")
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {c['subdir']}: {e}")
    total_after = len(getattr(repo, "permits", []))
    print(f"seed complete: +{total_added} added, repo now has {total_after} permits "
          f"across {len(getattr(repo, 'jurisdictions', []))} jurisdictions")


if __name__ == "__main__":
    run()
