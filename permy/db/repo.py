from __future__ import annotations

"""Repository — the data access layer.

This is the single seam between the API routers and storage. The MVP ships an
in-memory implementation seeded from a real Austin Socrata fixture so the API
works end-to-end (and tests run with zero infra). A Postgres implementation
with the same interface drops in for production — see `permy/db/pg_repo.py`.

Routers NEVER touch SQL or adapters directly; they go through `get_repo()`.
"""
import json  # noqa: E402
from datetime import date, datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Tuple  # noqa: E402

from permy.adapters.austin import AustinAdapter  # noqa: E402
from permy.core.confidence import (  # noqa: E402
    overall_confidence,
)
from permy.models.schemas import (  # noqa: E402
    Alert,
    AlertCreate,
    Contractor,
    ContractorActivity,
    CoverageCity,
    CoverageResponse,
    Enrichment,
    IntelligenceRequest,
    IntelligenceResponse,
    MarketScore,
    Permit,
    PermitTimelineEntry,
    Property,
    PropertyTimeline,
    RankedLead,
    RiskFlag,
)
from permy.scoring.lead_score import score_permit  # noqa: E402


class Repo:
    """In-memory repository. Production swaps this for Postgres-backed Repo."""

    def __init__(self) -> None:
        self.permits: List[Permit] = []
        self.contractors: Dict[str, Contractor] = {}
        self.contractor_activity: Dict[str, Dict[str, Any]] = {}
        self.properties: Dict[str, Property] = {}
        self.markets: Dict[str, MarketScore] = {}
        self.alerts: Dict[str, Alert] = {}
        self._alert_seq = 0
        self.jurisdictions: List[Dict[str, Any]] = []

    # ---- seeding ----
    def seed_from_fixture(self, adapter, fixture_path: Path) -> int:
        """Load real records from a recorded fixture + enrich. Works for any city adapter.

        Handles BOTH fixture shapes:
          * Socrata: a bare JSON array ``[{...}, {...}]``
          * ArcGIS: ``{"features":[{"attributes":{...},"geometry":{...}}], "spatialReference":{...}}``
        Dedupes by canonical_uid so re-seeding never duplicates (idempotent).
        """
        data = json.loads(fixture_path.read_text())
        if isinstance(data, dict) and "features" in data:
            # ArcGIS shape — record the spatial reference so ArcGIS adapters can
            # reproject projected geometry (Miami StatePlane → WGS84). Prefer
            # latestWkid (the current EPSG code) over the deprecated wkid, since
            # pyproj may not recognise legacy codes like 102658.
            sr = data.get("spatialReference")
            if isinstance(sr, dict) and hasattr(adapter, "_geometry_wkid"):
                adapter._geometry_wkid = sr.get("latestWkid") or sr.get("wkid")
            rows = data["features"]
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        existing_uids = {p.canonical_uid for p in self.permits}
        added = 0
        for raw in rows:
            p = adapter.normalize(raw)
            if p.canonical_uid in existing_uids:
                continue  # idempotent — never duplicate on re-seed
            # enrich: confidence + score (general persona for storage; reranked per-call)
            fields = {
                "valuation_usd": p.valuation_usd, "issued_date": p.dates.issued,
                "trade_category": p.trade_category, "contractor_id": p.contractor.name if p.contractor else None,
                "geom": p.address.lat, "description": p.description,
            }
            p.enrichment = Enrichment(
                confidence=overall_confidence(adapter.source_portal, True, p.last_checked_at, fields),
            )
            b = score_permit(p, persona="general")
            p.enrichment.lead_score = b.lead_score
            p.enrichment.recommended_action = b.recommended_action  # type: ignore
            p.enrichment.reason = b.reason
            p.enrichment.dq_flags = b.dq_flags
            self.permits.append(p)
            self._index_contractor(p)
            self._index_property(p)
            existing_uids.add(p.canonical_uid)
            added += 1
        self._recompute_markets()
        meta = adapter.source_meta()
        if meta["jurisdiction_slug"] not in {j["jurisdiction_slug"] for j in self.jurisdictions}:
            self.jurisdictions.append(meta)
        return added

    def seed_from_austin_fixture(self, fixture_path: Path) -> int:
        """Back-compat: seed Austin specifically."""
        return self.seed_from_fixture(AustinAdapter(), fixture_path)

    def _index_contractor(self, p: Permit) -> None:
        if not p.contractor or not p.contractor.name:
            return
        key = f"{p.jurisdiction_slug}:{p.contractor.name.lower()}"
        c = self.contractors.get(key)
        if c is None:
            c = Contractor(
                id=key, canonical_uid=key, name=p.contractor.name,
                license_number=p.contractor.license, trade=p.contractor.trade,
                phone=p.contractor.phone, city=p.address.city, state=p.address.state,
                zip=p.address.zip, confidence=p.enrichment.confidence,
                source_url=p.source_url,
            )
            self.contractors[key] = c
            self.contractor_activity[key] = {
                "permit_count": 0, "total_valuation_usd": 0.0,
                "trade_mix": {}, "active_cities": set(), "dates": [],
            }
        act = self.contractor_activity[key]
        act["permit_count"] += 1
        act["total_valuation_usd"] += float(p.valuation_usd or 0)
        t = p.trade_category
        act["trade_mix"][t] = act["trade_mix"].get(t, 0) + 1
        if p.address.city:
            act["active_cities"].add(p.address.city.title())
        act["dates"].append(p.dates.issued or p.dates.applied)

    def _index_property(self, p: Permit) -> None:
        key = p.address.full.lower()
        prop = self.properties.get(key)
        if prop is None:
            prop = Property(
                id=key, canonical_uid=key, full_address=p.address.full,
                street=p.address.street, city=p.address.city, state=p.address.state,
                zip=p.address.zip, jurisdiction_slug=p.jurisdiction_slug,
                parcel_id=p.parcel_id, coverage_status="covered",
            )
            self.properties[key] = prop
        prop.permit_count += 1
        ld = p.dates.issued or p.dates.applied
        if ld and (prop.last_permit_date is None or ld > prop.last_permit_date):
            prop.last_permit_date = ld

    def _recompute_markets(self) -> None:
        by_zip: Dict[str, List[Permit]] = {}
        for p in self.permits:
            if p.address.zip:
                by_zip.setdefault(p.address.zip, []).append(p)
        for zipc, ps in by_zip.items():
            total_val = sum(float(p.valuation_usd or 0) for p in ps)
            trade_mix: Dict[str, int] = {}
            for p in ps:
                trade_mix[p.trade_category] = trade_mix.get(p.trade_category, 0) + 1
            # crude hotspot: scale by count + value
            hotspot = min(100, int(50 + len(ps) * 5 + total_val / 100_000))
            self.markets[zipc] = MarketScore(
                zip=zipc, as_of_date=date.today(),
                permit_count_30d=len(ps), permit_count_90d=len(ps),
                total_value_30d=total_val, total_value_90d=total_val,
                trade_mix=trade_mix, mom_delta_pct=None,
                top_contractors=[], hotspot_score=hotspot,
                narrative=f"{len(ps)} permits, ~${total_val:,.0f} declared value in {zipc}.",
            )

    # ---- queries ----
    def search_permits(self, params: Dict[str, Any]) -> Tuple[List[Permit], int]:
        results = list(self.permits)
        if params.get("city"):
            results = [p for p in results if (p.address.city or "").lower() == params["city"].lower()]
        if params.get("state"):
            results = [p for p in results if (p.address.state or "").lower() == params["state"].lower()]
        if params.get("zip"):
            results = [p for p in results if (p.address.zip or "") == params["zip"]]
        if params.get("trade"):
            results = [p for p in results if p.trade_category == params["trade"]]
        if params.get("permit_type"):
            results = [p for p in results if (p.permit_type_normalized or "").lower() == params["permit_type"].lower()]
        if params.get("status"):
            results = [p for p in results if p.current_status == params["status"]]
        if params.get("contractor"):
            q = params["contractor"].lower()
            results = [p for p in results if p.contractor and q in (p.contractor.name or "").lower()]
        if params.get("keyword"):
            q = params["keyword"].lower()
            results = [p for p in results if q in (p.description or "").lower()]
        if params.get("min_valuation") is not None:
            results = [p for p in results if p.valuation_usd and p.valuation_usd >= params["min_valuation"]]
        if params.get("max_valuation") is not None:
            results = [p for p in results if p.valuation_usd and p.valuation_usd <= params["max_valuation"]]
        if params.get("issued_after"):
            results = [p for p in results if p.dates.issued and p.dates.issued >= params["issued_after"]]
        if params.get("issued_before"):
            results = [p for p in results if p.dates.issued and p.dates.issued <= params["issued_before"]]
        # sort
        sort = params.get("sort", "issued_date")
        reverse = params.get("sort_dir", "desc") == "desc"
        def _key(p: Permit):
            if sort == "valuation_usd":
                return (p.valuation_usd or 0)
            if sort == "lead_score":
                return (p.enrichment.lead_score or 0)
            return p.dates.issued or date.min
        results.sort(key=_key, reverse=reverse)
        total = len(results)
        page = max(1, int(params.get("page", 1)))
        limit = max(1, min(100, int(params.get("limit", 25))))
        start = (page - 1) * limit
        return results[start:start + limit], total

    def get_permit(self, permit_id: str) -> Optional[Permit]:
        for p in self.permits:
            if p.id == permit_id or p.canonical_uid == permit_id or p.source_permit_id == permit_id:
                return p
        return None

    def resolve_property(self, address_str: str) -> Optional[Property]:
        key = address_str.lower().strip()
        # fuzzy: prefix match
        for k, prop in self.properties.items():
            if key in k or k in key:
                return prop
        return None

    def property_timeline(self, property_id: str) -> Optional[PropertyTimeline]:
        prop = self.properties.get(property_id) or self.resolve_property(property_id)
        if prop is None:
            return None
        ps = [p for p in self.permits if p.address.full.lower() == prop.full_address.lower()]
        ps.sort(key=lambda p: p.dates.issued or p.dates.applied or date.min, reverse=True)
        entries = [
            PermitTimelineEntry(
                id=p.id, permit_type_normalized=p.permit_type_normalized,
                work_class=p.work_class, trade_category=p.trade_category,
                valuation_usd=p.valuation_usd, issued_date=p.dates.issued,
                current_status=p.current_status, contractor=p.contractor, description=p.description,
            ) for p in ps
        ]
        total_val = sum(float(p.valuation_usd or 0) for p in ps)
        return PropertyTimeline(
            property=prop, permits=entries, total_permits=len(ps),
            total_valuation_usd=total_val if ps else None,
            last_activity=prop.last_permit_date, unpermitted_work_flag=False,
        )

    def search_contractors(self, params: Dict[str, Any]) -> Tuple[List[Contractor], int]:
        results = list(self.contractors.values())
        if params.get("name"):
            q = params["name"].lower()
            results = [c for c in results if q in c.name.lower()]
        if params.get("trade"):
            results = [c for c in results if (c.trade or "").lower() == params["trade"].lower()]
        if params.get("license"):
            results = [c for c in results if c.license_number and params["license"] in c.license_number]
        if params.get("city"):
            q = params["city"].lower()
            results = [c for c in results if c.city and q in c.city.lower()]
        # sort by activity
        results.sort(key=lambda c: self.contractor_activity[c.id]["permit_count"], reverse=True)
        total = len(results)
        page = max(1, int(params.get("page", 1)))
        limit = max(1, min(100, int(params.get("limit", 25))))
        start = (page - 1) * limit
        return results[start:start + limit], total

    def contractor_activity_get(self, contractor_id: str) -> Optional[ContractorActivity]:
        c = self.contractors.get(contractor_id)
        if c is None:
            return None
        act = self.contractor_activity[contractor_id]
        tv = act["total_valuation_usd"]
        band = "<50k" if tv < 50_000 else ("50k-500k" if tv < 500_000 else "500k+")
        # momentum: fraction of permits in last 90 days
        dates = act["dates"]
        if dates:
            recent = sum(1 for d in dates if d and (date.today() - d).days <= 90)
            momentum = min(1.0, recent / max(1, len(dates)))
        else:
            momentum = 0.0
        return ContractorActivity(
            contractor=c, permit_count=act["permit_count"],
            total_valuation_usd=tv, trade_mix=act["trade_mix"],
            active_cities=sorted(act["active_cities"]), value_band=band,  # type: ignore
            momentum=momentum,
        )

    def market_score(self, zipc: str) -> Optional[MarketScore]:
        return self.markets.get(zipc)

    def rank_leads(self, params: Dict[str, Any]) -> Tuple[List[RankedLead], int]:
        from permy.scoring.lead_score import score_permit
        persona = params.get("persona", "general")
        permits, total = self.search_permits(params)
        hotspots = {z: m.hotspot_score for z, m in self.markets.items()}
        ranked = []
        for p in permits:
            b = score_permit(p, persona=persona, market_hotspot=hotspots.get(p.address.zip))
            ranked.append(RankedLead(
                permit=p, lead_score=b.lead_score,
                recommended_action=b.recommended_action, reason=b.reason, persona=persona,
            ))
        ranked.sort(key=lambda r: r.lead_score, reverse=True)
        limit = max(1, min(100, int(params.get("limit", 25))))
        return ranked[:limit], total

    def intelligence(self, req: IntelligenceRequest) -> IntelligenceResponse:
        from permy.scoring.lead_score import score_permit
        prop = None
        permits: List[Permit] = []
        if req.permit_id:
            p = self.get_permit(req.permit_id)
            if p:
                permits = [p]
        elif req.address:
            prop = self.resolve_property(req.address)
            if prop:
                tl = self.property_timeline(prop.id)
                if tl:
                    permits = [self.get_permit(e.id) for e in tl.permits]
                    permits = [x for x in permits if x]
        market = self.markets.get(prop.zip) if prop else None
        # development score: blend permit count + market hotspot
        dev = 50
        if prop:
            dev = min(100, 30 + prop.permit_count * 8)
        if market:
            dev = int(0.5 * dev + 0.5 * market.hotspot_score)
        risk_flags: List[RiskFlag] = []
        if permits and any(p.trade_category == "unknown" for p in permits):
            risk_flags.append(RiskFlag(flag="unclassified_trade", severity="warning"))
        if not permits:
            risk_flags.append(RiskFlag(flag="no_permit_history", severity="info",
                                       detail="No permits found for this property; possible unpermitted work."))
        action = None
        lead = None
        if permits:
            b = score_permit(permits[0], persona=req.persona,
                             market_hotspot=market.hotspot_score if market else None)
            action = b.recommended_action
            lead = b.lead_score
        narrative = None
        if market:
            narrative = market.narrative
        elif prop:
            narrative = f"{prop.permit_count} permits on record at this property."
        source_links = list({p.source_url for p in permits if p.source_url})
        conf = max([p.enrichment.confidence for p in permits], default=0.0)
        return IntelligenceResponse(
            input=req, property=prop, permits=permits,
            development_score=dev,
            permit_activity={"count": len(permits),
                             "total_valuation": sum(float(p.valuation_usd or 0) for p in permits)},
            risk_flags=risk_flags, market_context=narrative, market=market,
            recommended_action=action, lead_score=lead,
            source_links=source_links, confidence=conf,
        )

    # ---- alerts ----
    def create_alert(self, owner_key: str, body: AlertCreate) -> Alert:
        self._alert_seq += 1
        aid = str(self._alert_seq)
        a = Alert(
            id=aid, persona=body.persona, query=body.query,
            webhook_url=body.webhook_url, is_active=True, created_at=datetime.now(timezone.utc),
        )
        self.alerts[aid] = a
        return a

    def list_alerts(self, owner_key: str) -> List[Alert]:
        return list(self.alerts.values())

    def list_active_alerts(self) -> List[Alert]:
        """All active alerts across owners — used by the webhook worker to match
        new permits against saved searches."""
        return [a for a in self.alerts.values() if a.is_active]

    def delete_alert(self, owner_key: str, alert_id: str) -> bool:
        return self.alerts.pop(alert_id, None) is not None

    # ---- coverage ----
    def coverage(self) -> CoverageResponse:
        cities = []
        for j in self.jurisdictions:
            cov = j.get("coverage", {})
            cities.append(CoverageCity(
                jurisdiction_slug=j["jurisdiction_slug"], city=j["city"], state=j["state"],
                source_portal=j["source_portal"], source_name=j["source_name"],
                is_live=j.get("is_live", True),
                last_ingested_at=datetime.now(timezone.utc),
                ingest_cadence=j.get("ingest_cadence", "daily"),
                fields={
                    "permits": cov.get("permits", True), "valuation": cov.get("valuation", False),
                    "contractor": cov.get("contractor", False), "owner": cov.get("owner", False),
                    "phone": cov.get("phone", False), "geocode": cov.get("geocode", False),
                },
            ))
        return CoverageResponse(cities=cities, total=len(cities))


# ---- singleton ----
_repo: Optional[Repo] = None


def get_repo() -> Repo:
    """Get the configured repo. PG-backed when DATABASE_URL is reachable + schema
    present; otherwise the in-memory repo seeded from recorded fixtures (so the API
    works with zero infra — great for dev, tests, and demos)."""
    global _repo
    if _repo is None:
        from permy.core.config import settings as _s
        if _s.env not in ("local", "test") and _get_pg_repo_or_none() is not None:
            _repo = _get_pg_repo_or_none()
            return _repo
        _repo = Repo()
        # seed from recorded fixtures for ALL SEVEN MVP cities (no DB needed)
        _seed_all_cities_from_fixtures(_repo)
    return _repo


# (adapter import path, fixture subdir) for every MVP city
_CITY_FIXTURES = (
    ("permy.adapters.austin", "AustinAdapter", "austin"),
    ("permy.adapters.nyc", "NYCAdapter", "nyc"),
    ("permy.adapters.chicago", "ChicagoAdapter", "chicago"),
    ("permy.adapters.sf", "SFAdapter", "sf"),
    ("permy.adapters.seattle", "SeattleAdapter", "seattle"),
    ("permy.adapters.la", "LAAdapter", "la"),
    ("permy.adapters.miami", "MiamiAdapter", "miami"),
    ("permy.adapters.orlando", "OrlandoAdapter", "orlando"),
    ("permy.adapters.fortworth", "FortWorthAdapter", "fortworth"),
)


def _seed_all_cities_from_fixtures(repo: "Repo") -> None:
    """Seed the in-memory repo from every recorded fixture that exists."""
    import importlib
    fixtures_root = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"
    for mod_path, cls_name, subdir in _CITY_FIXTURES:
        fx = fixtures_root / subdir / "sample_3.json"
        if not fx.exists():
            continue
        mod = importlib.import_module(mod_path)
        adapter_cls = getattr(mod, cls_name)
        repo.seed_from_fixture(adapter_cls(), fx)


def _get_pg_repo_or_none():
    """Return a PostgresRepo if the DB is reachable + schema present, else None.

    Kept lazy + defensive: in dev/test (no Postgres) this returns None and the
    in-memory repo is used. Never raises — failure to connect just means 'use memory'.
    """
    try:
        from permy.db.pg_repo import PostgresRepo  # imported lazily
        return PostgresRepo.connect_or_none()
    except Exception:  # noqa: BLE001
        return None


def reset_repo() -> None:
    global _repo
    _repo = None
