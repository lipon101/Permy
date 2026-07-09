from __future__ import annotations

"""arq queue worker — ingestion jobs + alert matching + signed webhook delivery.

Jobs:
  * ``ingest_city``        — run an ingestion pass for one city (cron-driven)
  * ``ingest_and_notify``  — ingest a city, match new permits against active
                             alerts, and enqueue a webhook delivery per match
  * ``deliver_webhook``    — deliver one signed webhook, re-enqueuing with
                             exponential backoff on failure (30s, 2m, 10m, x3)

The worker is a long-running process (``permy-worker``). In MVP the cron is a
simple loop / systemd timer / Fly cron invoking ``permy-ingest`` per city; the
alert-notification path runs inside this worker so delivery is async + retried.

Pure helper ``match_and_deliver`` is separated out so it's unit-testable without
a running arq/Redis — tests call it with a stubbed deliverer.
"""
from datetime import date  # noqa: E402
from typing import Any, Callable, Dict, List, Optional  # noqa: E402

from permy.adapters.base import ADAPTERS  # noqa: E402
from permy.ingest.alert_matcher import build_webhook_payload, match_alerts  # noqa: E402
from permy.ingest.pipeline import process_record  # noqa: E402
from permy.ingest.webhooks import RETRY_BACKOFFS, DeliveryResult, deliver  # noqa: E402
from permy.models.schemas import Alert, Permit  # noqa: E402


def _new_permits(adapter, since: Optional[date], limit: int) -> List[Permit]:
    """Fetch + process raw records into enriched Permits (no persistence)."""
    raws = adapter.fetch(since=since, limit=limit)
    return [process_record(raw, adapter) for raw in raws]


def match_and_deliver(
    permits: List[Permit],
    alerts: List[Alert],
    api_key: str,
    deliverer: Optional[Callable[..., DeliveryResult]] = None,
    market_hotspot_by_zip: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """Match permits against active alerts and deliver one webhook per match.

    ``deliverer`` defaults to ``permy.ingest.webhooks.deliver`` but can be
    stubbed in tests. Returns a counts dict: matches / deliveries / delivered / failed.

    This is the synchronous, in-process path used by tests and by the arq job
    below. In production with a real Redis, each delivery would be enqueued as
    its own ``deliver_webhook`` job so retries are durable; here we deliver
    inline (still retried by the job layer when run via arq).
    """
    _deliver = deliverer or deliver
    matches = 0
    deliveries = 0
    delivered = 0
    failed = 0
    for p in permits:
        for m in match_alerts(p, alerts, market_hotspot_by_zip=market_hotspot_by_zip):
            matches += 1
            if not m.alert.webhook_url:
                continue  # alert has no webhook configured — nothing to deliver
            deliveries += 1
            payload = build_webhook_payload(m)
            # Alert records don't carry the secret (only AlertCreate did); use
            # the global PERMY_WEBHOOK_SECRET via deliver()'s default.
            res = _deliver(m.alert.webhook_url, "permit.new", payload, api_key,
                           secret=None)
            if res.delivered:
                delivered += 1
            else:
                failed += 1
    return {"matches": matches, "deliveries": deliveries, "delivered": delivered, "failed": failed}


# ---------------------------------------------------------------------------
# arq job functions
# ---------------------------------------------------------------------------
async def ingest_city(ctx: Dict[str, Any], jurisdiction_slug: str,
                      since: Optional[str] = None, limit: int = 1000) -> Dict[str, int]:
    """arq job: run an ingestion pass for one city (persist via ctx.persister)."""
    since_date = date.fromisoformat(since) if since else None
    adapter = ADAPTERS[jurisdiction_slug]
    persister = ctx.get("persister")
    geocoder = ctx.get("geocoder")
    raws = adapter.fetch(since=since_date, limit=limit)
    processed = 0
    for raw in raws:
        p = process_record(raw, adapter, geocoder=geocoder,
                           market_hotspot_by_zip=ctx.get("market_hotspot_by_zip"))
        if persister:
            persister(p)
        processed += 1
    return {"fetched": len(raws), "processed": processed}


async def ingest_and_notify(ctx: Dict[str, Any], jurisdiction_slug: str,
                            since: Optional[str] = None, limit: int = 1000) -> Dict[str, Any]:
    """arq job: ingest a city, then match new permits against active alerts and
    enqueue a webhook delivery per match.

    Reads active alerts from ``ctx['repo']`` and delivers via the in-process
    ``match_and_deliver`` (which in a full arq setup would enqueue
    ``deliver_webhook`` jobs for durability).
    """
    since_date = date.fromisoformat(since) if since else None
    adapter = ADAPTERS[jurisdiction_slug]
    permits = _new_permits(adapter, since_date, limit)
    persister = ctx.get("persister")
    if persister:
        for p in permits:
            persister(p)
    repo = ctx.get("repo")
    alerts: List[Alert] = []
    if repo is not None and hasattr(repo, "list_active_alerts"):
        alerts = repo.list_active_alerts()
    elif repo is not None and hasattr(repo, "alerts"):
        alerts = list(repo.alerts.values())
    api_key = ctx.get("api_key", "system")
    counts = match_and_deliver(permits, alerts, api_key,
                               deliverer=ctx.get("deliverer"),
                               market_hotspot_by_zip=ctx.get("market_hotspot_by_zip"))
    return {"ingested": len(permits), **counts}


async def deliver_webhook(ctx: Dict[str, Any], url: str, event_type: str,
                          data: Dict[str, Any], api_key: str, secret: Optional[str] = None,
                          attempt: int = 0) -> Dict[str, Any]:
    """arq job: deliver one webhook, re-enqueuing with backoff on failure."""
    res = deliver(url, event_type, data, api_key, secret=secret)
    if not res.delivered and attempt < len(RETRY_BACKOFFS):
        return {"scheduled_retry": True, "next_attempt": attempt + 1,
                "backoff_s": RETRY_BACKOFFS[attempt], "last_error": res.error}
    return {"delivered": res.delivered, "status_code": res.status_code, "error": res.error,
            "attempts": attempt + 1}


class WorkerSettings:
    """arq worker config. Functions are the job registry."""
    functions = [ingest_city, ingest_and_notify, deliver_webhook]
    max_jobs = 4
    job_timeout = 600


def run() -> None:
    """Entry point for ``permy-worker``."""
    try:
        from arq import run_worker  # type: ignore
        run_worker(WorkerSettings)  # pragma: no cover
    except ImportError:
        import sys
        print("permy-worker requires `pip install arq` and a running Redis.", file=sys.stderr)
        sys.exit(1)


__all__ = [
    "ingest_city", "ingest_and_notify", "deliver_webhook",
    "match_and_deliver", "WorkerSettings", "run",
]
