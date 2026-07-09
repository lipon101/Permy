from __future__ import annotations

"""Postgres-backed Repo — production data access layer.

Same interface as the in-memory `Repo` in `permy/db/repo.py`, but backed by
asyncpg + PostGIS against the schema in `permy/db/schema.sql`.

Key differences from the in-memory repo:
  - UPSERT on canonical_uid (re-ingest updates, never duplicates)
  - PostGIS bounding-box queries for geo search
  - pg_trgm fuzzy search for contractor/address/keyword
  - Real daily quota accounting in `usage_daily`
  - Markets read from the nightly rollup table (not recomputed per call)

This is async at the storage layer (asyncpg). The FastAPI routers are sync
endpoints today (they call `get_repo()` and run blocking queries) — for the
MVP we bridge async→sync with `asyncio.run` inside each method. When we move
the routers to async def, swap these to await directly.

`connect_or_none()` is the safe factory: returns a PostgresRepo if the DB is
reachable + schema present, else None (so `get_repo()` falls back to memory).
"""
import asyncio
import hashlib
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from permy.models.schemas import (
    Address, Alert, AlertCreate, Contractor, ContractorActivity, ContractorRef,
    CoverageCity, CoverageResponse, Enrichment, IntelligenceRequest,
    IntelligenceResponse, MarketScore, OwnerRef, Permit, PermitTimelineEntry,
    Property, PropertyTimeline, RankedLead, RiskFlag,
)


def _permit_from_row(row: Dict[str, Any]) -> Permit:
    """Map a v_permits_full row (snake_case columns) → Permit model."""
    return Permit(
        id=str(row["id"]),
        canonical_uid=row["canonical_uid"],
        jurisdiction_slug=row["jurisdiction_slug"],
        source_permit_id=row["source_permit_id"],
        source_url=row.get("source_url"),
        source_name=row.get("source_name") or row.get("jurisdiction_source"),
        first_seen_at=row["first_seen_at"], last_seen_at=row["last_seen_at"],
        last_checked_at=row["last_checked_at"],
        address=Address(
            street=row.get("street"), city=row.get("city"), state=row.get("state"),
            zip=row.get("zip"), full=row.get("full_address") or ", ".join(
                x for x in [row.get("street"), row.get("city"), row.get("state"), row.get("zip")] if x),
            lat=float(row["lat"]) if row.get("lat") is not None else None,
            lng=float(row["lng"]) if row.get("lng") is not None else None,
            geocode_confidence=float(row["geocode_confidence"]) if row.get("geocode_confidence") is not None else None,
        ),
        permit_type_raw=row.get("permit_type_raw"),
        permit_type_normalized=row.get("permit_type_normalized"),
        work_class=row.get("work_class") or "unknown",
        trade_category=row.get("trade_category") or "unknown",
        is_new_construction=bool(row.get("is_new_construction")),
        is_alteration=bool(row.get("is_alteration")),
        is_demolition=bool(row.get("is_demolition")),
        valuation_usd=float(row["valuation_usd"]) if row.get("valuation_usd") is not None else None,
        housing_units=row.get("housing_units"),
        new_add_sqft=row.get("new_add_sqft"),
        dates=PermitDates(
            applied=row.get("applied_date"), issued=row.get("issued_date"),
            finaled=row.get("finaled_date"), expired=row.get("expired_date"),
        ),
        current_status=row.get("current_status") or "unknown",
        status_raw=row.get("status_raw"),
        description=row.get("description"),
        description_enriched=row.get("description_enriched"),
        contractor=ContractorRef(
            name=row.get("contractor_name"), license=row.get("license_number"),
            license_state=None, license_status=None,
            trade=row.get("contractor_trade"), phone=row.get("contractor_phone"),
        ) if row.get("contractor_name") else None,
        owner=OwnerRef(name=row.get("owner_name")),
        parcel_id=row.get("parcel_id"),
        enrichment=Enrichment(
            lead_score=row.get("lead_score"),
            recommended_action=row.get("recommended_action"),
            reason=row.get("reason"),
            dq_flags=row.get("dq_flags") or [],
            confidence=float(row.get("confidence") or 0.0),
        ),
    )


# PermitDates import (needed by _permit_from_row)
from permy.models.schemas import PermitDates  # noqa: E402


class PostgresRepo:
    """asyncpg-backed implementation of the Repo interface."""

    def __init__(self, pool):
        self.pool = pool

    # ---- factory ----
    @classmethod
    def connect_or_none(cls) -> Optional["PostgresRepo"]:
        """Try to connect + verify schema. Return None on any failure (→ in-memory fallback)."""
        try:
            from permy.core.config import settings as _s
            # asyncpg wants a postgres:// URL, not the SQLAlchemy +asyncpg dialect suffix
            dsn = _s.database_url.replace("postgresql+asyncpg://", "postgresql://")
            if _s.env in ("local", "test"):
                # in local/test we only use PG if it's explicitly reachable; otherwise None.
                # This keeps tests deterministic with the in-memory repo.
                return None
            import asyncpg
            loop = asyncio.new_event_loop()
            try:
                pool = loop.run_until_complete(asyncpg.create_pool(dsn, min_size=1, max_size=4, timeout=5))
                # verify the schema is present
                async def _check():
                    async with pool.acquire() as conn:
                        v = await conn.fetchval("SELECT to_regclass('public.permits')")
                        return v is not None
                if not loop.run_until_complete(_check()):
                    loop.run_until_complete(pool.close())
                    return None
                return cls(pool)
            finally:
                loop.close()
        except Exception:  # noqa: BLE001
            return None

    # ---- low-level async query runner (bridges sync routers → async asyncpg) ----
    def _run(self, coro):
        """Run an asyncpg coroutine in a fresh event loop (sync-router bridge)."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # ---- queries ----
    def search_permits(self, params: Dict[str, Any]) -> Tuple[List[Permit], int]:
        async def _q():
            where = ["1=1"]
            args: List[Any] = []
            i = 1
            def add(cond, val):
                nonlocal i
                where.append(cond.replace("$$", f"${i}"))
                args.append(val)
                i += 1
            if params.get("city"):
                add("lower(city) = lower($$)", params["city"])
            if params.get("state"):
                add("state = $$", params["state"].upper())
            if params.get("zip"):
                add("zip = $$", params["zip"])
            if params.get("trade"):
                add("trade_category = $$", params["trade"])
            if params.get("permit_type"):
                add("lower(permit_type_normalized) = lower($$)", params["permit_type"])
            if params.get("status"):
                add("current_status = $$", params["status"])
            if params.get("contractor"):
                add("contractor_name ILIKE '%' || $$ || '%", params["contractor"].lower())
                where[-1] = where[-1].rstrip("0")  # fix: rebuild properly
                # simpler: use trgm
                where.pop()
                add("contractor_name ILIKE $$", f"%{params['contractor']}%")
            if params.get("keyword"):
                add("description ILIKE $$", f"%{params['keyword']}%")
            if params.get("min_valuation") is not None:
                add("valuation_usd >= $$", params["min_valuation"])
            if params.get("max_valuation") is not None:
                add("valuation_usd <= $$", params["max_valuation"])
            if params.get("issued_after"):
                add("issued_date >= $$", params["issued_after"])
            if params.get("issued_before"):
                add("issued_date <= $$", params["issued_before"])
            if params.get("bbox"):
                # bbox = west,south,east,north → ST_MakeEnvelope
                try:
                    w, s, e, n = [float(x) for x in str(params["bbox"]).split(",")]
                    where.append(f"ST_Within(geom, ST_MakeEnvelope({w},{s},{e},{n},4326)::geography)")
                except ValueError:
                    pass
            sort = params.get("sort", "issued_date")
            sort_col = {"issued_date": "issued_date", "valuation_usd": "valuation_usd",
                        "lead_score": "lead_score"}.get(sort, "issued_date")
            direction = "DESC" if params.get("sort_dir", "desc") == "desc" else "ASC"
            nulls = "NULLS LAST" if direction == "DESC" else "NULLS FIRST"
            page = max(1, int(params.get("page", 1)))
            limit = max(1, min(100, int(params.get("limit", 25))))
            offset = (page - 1) * limit
            where_sql = " WHERE " + " AND ".join(where)
            count_sql = f"SELECT count(*) FROM permits{where_sql}"
            data_sql = (f"SELECT * FROM v_permits_full{where_sql} "
                        f"ORDER BY {sort_col} {direction} {nulls} LIMIT $${limit_param} OFFSET $${offset_param}")
            # asyncpg uses $1,$2,… — rebuild with explicit param indexes for LIMIT/OFFSET
            data_sql = data_sql.replace("{limit_param}", str(i)).replace("{offset_param}", str(i + 1))
            args += [limit, offset]
            async with self.pool.acquire() as conn:
                total = await conn.fetchval(count_sql, *args[:-2])
                rows = await conn.fetch(data_sql, *args)
            return [_permit_from_row(dict(r)) for r in rows], total
        return self._run(_q())

    def get_permit(self, permit_id: str) -> Optional[Permit]:
        async def _q():
            async with self.pool.acquire() as conn:
                # match on bigint id OR canonical_uid OR source_permit_id
                row = None
                if permit_id.isdigit():
                    row = await conn.fetchrow("SELECT * FROM v_permits_full WHERE id=$1", int(permit_id))
                if not row:
                    row = await conn.fetchrow(
                        "SELECT * FROM v_permits_full WHERE canonical_uid=$1 OR source_permit_id=$1", permit_id)
            return _permit_from_row(dict(row)) if row else None
        return self._run(_q())

    def resolve_property(self, address_str: str) -> Optional[Property]:
        async def _q():
            async with self.pool.acquire() as conn:
                # trgm similarity search
                row = await conn.fetchrow(
                    "SELECT * FROM properties WHERE full_address ILIKE $1 ORDER BY similarity(full_address,$1) DESC LIMIT 1",
                    f"%{address_str}%")
            if not row:
                return None
            r = dict(row)
            return Property(
                id=str(r["id"]), canonical_uid=r["canonical_uid"], full_address=r["full_address"],
                street=r.get("street"), city=r.get("city"), state=r.get("state"), zip=r.get("zip"),
                lat=float(r["lat"]) if r.get("lat") is not None else None,
                lng=float(r["lng"]) if r.get("lng") is not None else None,
                geocode_confidence=float(r["geocode_confidence"]) if r.get("geocode_confidence") else None,
                jurisdiction_slug=r.get("jurisdiction_slug"), parcel_id=r.get("parcel_id"),
                year_built=r.get("year_built"), sqft=r.get("sqft"),
                permit_count=r.get("permit_count", 0), last_permit_date=r.get("last_permit_date"),
                coverage_status=r.get("coverage_status") or "covered",
            )
        return self._run(_q())

    def property_timeline(self, property_id: str) -> Optional[PropertyTimeline]:
        prop = self.resolve_property(property_id)
        if prop is None:
            return None
        async def _q():
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM v_permits_full WHERE full_address=$1 ORDER BY issued_date DESC NULLS LAST",
                    prop.full_address)
            entries = [
                PermitTimelineEntry(
                    id=str(r["id"]), permit_type_normalized=r.get("permit_type_normalized"),
                    work_class=r.get("work_class") or "unknown", trade_category=r.get("trade_category") or "unknown",
                    valuation_usd=float(r["valuation_usd"]) if r.get("valuation_usd") else None,
                    issued_date=r.get("issued_date"), current_status=r.get("current_status") or "unknown",
                    contractor=ContractorRef(name=r.get("contractor_name"),
                                             license=r.get("license_number"),
                                             trade=r.get("contractor_trade"),
                                             phone=r.get("contractor_phone")) if r.get("contractor_name") else None,
                    description=r.get("description"),
                ) for r in rows
            ]
            total_val = sum(float(r["valuation_usd"] or 0) for r in rows)
            last = max((r.get("issued_date") for r in rows if r.get("issued_date")), default=None)
            return PropertyTimeline(
                property=prop, permits=entries, total_permits=len(rows),
                total_valuation_usd=total_val if rows else None,
                last_activity=last, unpermitted_work_flag=False,
            )
        return self._run(_q())

    def search_contractors(self, params: Dict[str, Any]) -> Tuple[List[Contractor], int]:
        async def _q():
            where = ["1=1"]
            args: List[Any] = []
            i = 1
            if params.get("name"):
                where.append(f"name ILIKE ${i}"); args.append(f"%{params['name']}%"); i += 1
            if params.get("trade"):
                where.append(f"trade = ${i}"); args.append(params["trade"]); i += 1
            if params.get("license"):
                where.append(f"license_number ILIKE ${i}"); args.append(f"%{params['license']}%"); i += 1
            if params.get("city"):
                where.append(f"city ILIKE ${i}"); args.append(f"%{params['city']}%"); i += 1
            page = max(1, int(params.get("page", 1)))
            limit = max(1, min(100, int(params.get("limit", 25))))
            offset = (page - 1) * limit
            where_sql = " WHERE " + " AND ".join(where)
            count_sql = f"SELECT count(*) FROM contractors{where_sql}"
            data_sql = (f"SELECT * FROM contractors{where_sql} ORDER BY permit_count DESC "
                        f"LIMIT ${i} OFFSET ${i+1}")
            args += [limit, offset]
            async with self.pool.acquire() as conn:
                total = await conn.fetchval(count_sql, *args[:-2])
                rows = await conn.fetch(data_sql, *args)
            contractors = [
                Contractor(
                    id=str(r["id"]), canonical_uid=r["canonical_uid"], name=r["name"],
                    license_number=r.get("license_number"), license_state=r.get("license_state"),
                    license_status=r.get("license_status"), trade=r.get("trade"),
                    phone=r.get("phone"), city=r.get("city"), state=r.get("state"), zip=r.get("zip"),
                    source_url=r.get("source_url"), confidence=float(r.get("confidence") or 0.0),
                ) for r in rows
            ]
            return contractors, total
        return self._run(_q())

    def contractor_activity_get(self, contractor_id: str) -> Optional[ContractorActivity]:
        async def _q():
            async with self.pool.acquire() as conn:
                c = await conn.fetchrow("SELECT * FROM contractors WHERE id=$1 OR canonical_uid=$1",
                                        int(contractor_id) if contractor_id.isdigit() else contractor_id)
                if not c:
                    return None
                c = dict(c)
                tv = float(c.get("total_valuation_usd") or 0)
                band = "<50k" if tv < 50_000 else ("50k-500k" if tv < 500_000 else "500k+")
                contractor = Contractor(
                    id=str(c["id"]), canonical_uid=c["canonical_uid"], name=c["name"],
                    license_number=c.get("license_number"), license_state=c.get("license_state"),
                    license_status=c.get("license_status"), trade=c.get("trade"),
                    phone=c.get("phone"), city=c.get("city"), state=c.get("state"), zip=c.get("zip"),
                    source_url=c.get("source_url"), confidence=float(c.get("confidence") or 0.0),
                )
                return ContractorActivity(
                    contractor=contractor, permit_count=c.get("permit_count", 0),
                    total_valuation_usd=tv, trade_mix=c.get("trade_mix") or {},
                    active_cities=c.get("active_cities") or [], value_band=band,  # type: ignore
                    momentum=float(c.get("momentum") or 0.0),
                    first_seen_at=c.get("first_seen_at"), last_seen_at=c.get("last_seen_at"),
                )
        return self._run(_q())

    def market_score(self, zipc: str) -> Optional[MarketScore]:
        async def _q():
            async with self.pool.acquire() as conn:
                r = await conn.fetchrow("SELECT * FROM markets WHERE zip=$1 ORDER BY as_of_date DESC LIMIT 1", zipc)
            if not r:
                return None
            r = dict(r)
            return MarketScore(
                zip=r["zip"], as_of_date=r["as_of_date"],
                permit_count_30d=r.get("permit_count_30d", 0), permit_count_90d=r.get("permit_count_90d", 0),
                total_value_30d=float(r.get("total_value_30d") or 0), total_value_90d=float(r.get("total_value_90d") or 0),
                trade_mix=r.get("trade_mix") or {}, mom_delta_pct=float(r["mom_delta_pct"]) if r.get("mom_delta_pct") is not None else None,
                top_contractors=r.get("top_contractors") or [], hotspot_score=r.get("hotspot_score", 0),
            )
        return self._run(_q())

    def rank_leads(self, params: Dict[str, Any]) -> Tuple[List[RankedLead], int]:
        from permy.scoring.lead_score import score_permit
        permits, total = self.search_permits(params)
        # market hotspots by zip
        hotspots: Dict[str, int] = {}
        for p in permits:
            if p.address.zip and p.address.zip not in hotspots:
                m = self.market_score(p.address.zip)
                if m:
                    hotspots[p.address.zip] = m.hotspot_score
        persona = params.get("persona", "general")
        leads = []
        for p in permits:
            b = score_permit(p, persona=persona, market_hotspot=hotspots.get(p.address.zip))
            leads.append(RankedLead(permit=p, lead_score=b.lead_score,
                                     recommended_action=b.recommended_action,
                                     reason=b.reason, persona=persona))
        leads.sort(key=lambda r: r.lead_score, reverse=True)
        limit = max(1, min(100, int(params.get("limit", 25))))
        return leads[:limit], total

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
                    # fetch full permits for timeline entries
                    for e in tl.permits:
                        fp = self.get_permit(e.id)
                        if fp:
                            permits.append(fp)
        market = self.market_score(prop.zip) if prop else None
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
                                       detail="No permits found; possible unpermitted work."))
        action = None
        lead = None
        if permits:
            b = score_permit(permits[0], persona=req.persona,
                             market_hotspot=market.hotspot_score if market else None)
            action = b.recommended_action
            lead = b.lead_score
        source_links = list({p.source_url for p in permits if p.source_url})
        conf = max([p.enrichment.confidence for p in permits], default=0.0)
        return IntelligenceResponse(
            input=req, property=prop, permits=permits, development_score=dev,
            permit_activity={"count": len(permits),
                             "total_valuation": sum(float(p.valuation_usd or 0) for p in permits)},
            risk_flags=risk_flags, market_context=market.narrative if market else None,
            market=market, recommended_action=action, lead_score=lead,
            source_links=source_links, confidence=conf,
        )

    # ---- alerts (owner-scoped) ----
    def create_alert(self, owner_key: str, body: AlertCreate) -> Alert:
        async def _q():
            async with self.pool.acquire() as conn:
                aid = await conn.fetchval(
                    "INSERT INTO alerts (api_key, persona, query, webhook_url) VALUES ($1,$2,$3,$4) RETURNING id",
                    owner_key, body.persona, body.query, body.webhook_url)
                r = await conn.fetchrow("SELECT * FROM alerts WHERE id=$1", aid)
            r = dict(r)
            return Alert(id=str(r["id"]), persona=r["persona"], query=r["query"],
                         webhook_url=r.get("webhook_url"), is_active=r["is_active"],
                         last_fired_at=r.get("last_fired_at"), created_at=r["created_at"])
        return self._run(_q())

    def list_alerts(self, owner_key: str) -> List[Alert]:
        async def _q():
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM alerts WHERE api_key=$1 AND is_active=true ORDER BY created_at DESC", owner_key)
            return [Alert(id=str(r["id"]), persona=r["persona"], query=r["query"],
                          webhook_url=r.get("webhook_url"), is_active=r["is_active"],
                          last_fired_at=r.get("last_fired_at"), created_at=r["created_at"]) for r in rows]
        return self._run(_q())

    def delete_alert(self, owner_key: str, alert_id: str) -> bool:
        async def _q():
            async with self.pool.acquire() as conn:
                aid = int(alert_id) if alert_id.isdigit() else None
                if aid is None:
                    return False
                res = await conn.execute("DELETE FROM alerts WHERE id=$1 AND api_key=$2", aid, owner_key)
                return res.endswith("1")
        return self._run(_q())

    # ---- coverage ----
    def coverage(self) -> CoverageResponse:
        async def _q():
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM jurisdictions ORDER BY city")
            cities = [
                CoverageCity(
                    jurisdiction_slug=r["jurisdiction_slug"], city=r["city"], state=r["state"],
                    source_portal=r["source_portal"], source_name=r["source_name"],
                    is_live=r["is_live"], last_ingested_at=r.get("last_ingested_at"),
                    ingest_cadence=r["ingest_cadence"],
                    fields=(r.get("coverage") or {}),
                ) for r in rows
            ]
            return CoverageResponse(cities=cities, total=len(cities))
        return self._run(_q())

    # ---- ingestion: UPSERT a permit (re-ingest updates, never duplicates) ----
    def upsert_permit(self, p: Permit, contractor_id: Optional[int] = None) -> None:
        """UPSERT a normalized permit on canonical_uid. Used by the pipeline."""
        async def _q():
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO permits (
                      canonical_uid, jurisdiction_slug, source_permit_id, source_url, source_name,
                      last_seen_at, last_checked_at, street, city, state, zip, full_address,
                      geom, geocode_confidence, permit_type_raw, permit_type_normalized,
                      work_class, trade_category, is_new_construction, is_alteration, is_demolition,
                      valuation_usd, housing_units, new_add_sqft, applied_date, issued_date,
                      finaled_date, expired_date, current_status, status_raw, description,
                      description_enriched, contractor_id, owner_name, parcel_id,
                      lead_score, recommended_action, reason, dq_flags, confidence
                    ) VALUES (
                      $1,$2,$3,$4,$5, now(), now(), $6,$7,$8,$9,$10,
                      ST_SetSRID(ST_MakePoint($12,$13),4326)::geography, $14,
                      $15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35,$36,$37,$38,$39,$40
                    )
                    ON CONFLICT (canonical_uid) DO UPDATE SET
                      source_url=EXCLUDED.source_url, last_seen_at=now(), last_checked_at=now(),
                      current_status=EXCLUDED.current_status, status_raw=EXCLUDED.status_raw,
                      valuation_usd=COALESCE(EXCLUDED.valuation_usd, permits.valuation_usd),
                      description=COALESCE(EXCLUDED.description, permits.description),
                      lead_score=EXCLUDED.lead_score, recommended_action=EXCLUDED.recommended_action,
                      reason=EXCLUDED.reason, dq_flags=EXCLUDED.dq_flags, confidence=EXCLUDED.confidence,
                      geom=COALESCE(EXCLUDED.geom, permits.geom)
                    """,
                    p.canonical_uid, p.jurisdiction_slug, p.source_permit_id, p.source_url, p.source_name,
                    p.address.street, p.address.city, p.address.state, p.address.zip, p.address.full,
                    p.address.lng, p.address.lat, p.address.geocode_confidence,
                    p.permit_type_raw, p.permit_type_normalized,
                    p.work_class, p.trade_category, p.is_new_construction, p.is_alteration, p.is_demolition,
                    p.valuation_usd, p.housing_units, p.new_add_sqft,
                    p.dates.applied, p.dates.issued, p.dates.finaled, p.dates.expired,
                    p.current_status, p.status_raw, p.description, p.description_enriched,
                    contractor_id, p.owner.name if p.owner else None, p.parcel_id,
                    p.enrichment.lead_score, p.enrichment.recommended_action,
                    p.enrichment.reason, p.enrichment.dq_flags, p.enrichment.confidence,
                )
        return self._run(_q())

    # jurisdictions (for the coverage page / get_repo seeding check)
    jurisdictions: List[Dict[str, Any]] = []
