from __future__ import annotations

"""Webhook signing + delivery.

Every webhook delivery is HMAC-SHA256 signed with the alert's secret (or the
global PERMY_WEBHOOK_SECRET fallback). Signature in `X-Permy-Signature` header;
event type in `X-Permy-Event`. Receivers SHOULD verify the signature.

Delivery contract: best-effort, at-least-once, within ~60s of new permits.
Retries with exponential backoff (30s, 2m, 10m) up to 3 attempts, then dead.
"""
import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any, Dict, Optional  # noqa: E402

import httpx  # noqa: E402

from permy.core.config import settings  # noqa: E402

RETRY_BACKOFFS = [30, 120, 600]  # seconds


def sign_payload(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def build_event(event_type: str, data: Dict[str, Any], api_key: str) -> bytes:
    envelope = {
        "event": event_type,
        "sent_at": int(time.time()),
        "api_key": api_key[:4] + "…",
        "data": data,
    }
    return json.dumps(envelope, separators=(",", ":")).encode()


@dataclass
class DeliveryResult:
    delivered: bool
    status_code: Optional[int]
    attempt: int
    error: Optional[str]


def deliver(
    url: str,
    event_type: str,
    data: Dict[str, Any],
    api_key: str,
    secret: Optional[str] = None,
    timeout: float = 10.0,
) -> DeliveryResult:
    """Synchronous single-attempt delivery (the worker handles retries)."""
    sec = secret or settings.webhook_secret
    payload = build_event(event_type, data, api_key)
    sig = sign_payload(payload, sec)
    headers = {
        "Content-Type": "application/json",
        "X-Permy-Signature": sig,
        "X-Permy-Event": event_type,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, content=payload, headers=headers)
        ok = 200 <= r.status_code < 300
        return DeliveryResult(delivered=ok, status_code=r.status_code, attempt=1,
                              error=None if ok else f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return DeliveryResult(delivered=False, status_code=None, attempt=1, error=str(e))


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Receiver-side verification helper (documented in docs)."""
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature)
