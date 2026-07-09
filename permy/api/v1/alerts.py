from __future__ import annotations

"""Alerts + webhooks (10–11)."""
import hashlib
import hmac
import json
import time
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from permy.db.repo import Repo, get_repo
from permy.middleware.auth import ApiKeyContext, require_feature
from permy.models.schemas import (
    Alert, AlertCreate, ErrorResponse, WebhookTestRequest, WebhookTestResponse,
)
from permy.core.config import settings

router = APIRouter(prefix="/v1", tags=["alerts & webhooks"])


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


@router.post("/alerts", response_model=Alert, summary="Create a saved search with optional webhook delivery")
def create_alert(
    body: AlertCreate,
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(require_feature("webhooks")),  # noqa: B008
) -> Alert:
    return repo.create_alert(ctx.key, body)


@router.get("/alerts", response_model=List[Alert], summary="List your saved searches")
def list_alerts(
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(require_feature("webhooks")),  # noqa: B008
) -> List[Alert]:
    return repo.list_alerts(ctx.key)


@router.delete("/alerts/{alert_id}", summary="Delete a saved search")
def delete_alert(
    alert_id: str,
    repo: Repo = Depends(get_repo),  # noqa: B008
    ctx: ApiKeyContext = Depends(require_feature("webhooks")),  # noqa: B008
):
    ok = repo.delete_alert(ctx.key, alert_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={
            "error": {"code": "not_found", "message": f"Alert '{alert_id}' not found.",
                      "docs_url": "https://docs.permy.dev/alerts"}})
    return {"deleted": True, "id": alert_id}


@router.post("/webhooks/test", response_model=WebhookTestResponse,
             summary="Send a signed HMAC test payload to your webhook URL")
def webhook_test(
    body: WebhookTestRequest,
    ctx: ApiKeyContext = Depends(require_feature("webhooks")),  # noqa: B008
) -> WebhookTestResponse:
    secret = body.secret or settings.webhook_secret
    payload = json.dumps({
        "event": "webhook.test",
        "sent_at": int(time.time()),
        "api_key": ctx.key[:4] + "…",
    }, separators=(",", ":")).encode()
    sig = _sign(payload, secret)
    headers = {
        "Content-Type": "application/json",
        "X-Permy-Signature": sig,
        "X-Permy-Event": "webhook.test",
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(body.url, content=payload, headers=headers)
        latency = int((time.time() - t0) * 1000)
        delivered = 200 <= r.status_code < 300
        return WebhookTestResponse(
            delivered=delivered, status_code=r.status_code, latency_ms=latency,
            error=None if delivered else f"HTTP {r.status_code}",
        )
    except Exception as e:  # noqa: BLE001
        return WebhookTestResponse(delivered=False, status_code=None, latency_ms=None, error=str(e))
