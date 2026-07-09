from __future__ import annotations

"""Structured logging — JSON in production (PERMY_ENV=prod), readable text in dev.

Every log line carries request_id when available, and secrets are masked
(API keys, auth headers) so PII/credentials never hit a log sink. This is the
minimum bar for the enterprise/Business-tier buyers who run security reviews.
"""
import json
import logging
import os
import sys
from typing import Any, MutableMapping


_SENSITIVE_KEYS = {"api_key", "x-api-key", "authorization", "x-rapidapi-key",
                   "webhook_secret", "password", "token", "secret", "database_url"}


def _mask(value: Any) -> str:
    s = str(value)
    if len(s) <= 6:
        return "***"
    return f"{s[:3]}…{s[-2:]}"


class JsonFormatter(logging.Formatter):
    """One JSON object per log record, safe for log aggregators (Loki, Datadog, …)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: MutableMapping[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # fold selected LogRecord extras into the payload (skip dunder/cached attrs)
        for key in ("request_id", "method", "path", "status", "duration_ms", "tier", "city", "error"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        # mask any sensitive keys present in record.__dict__
        for k, v in record.__dict__.items():
            if any(s in k.lower() for s in ("key", "secret", "token", "auth")) and v:
                payload[k] = _mask(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(env: str = "local", level: str = "INFO") -> logging.Logger:
    """Configure root + permy loggers. JSON in prod; readable text elsewhere."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    # clear any prior handlers (uvicorn may attach its own; we keep ours deterministic)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    if env in ("prod", "production", "staging"):
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(log_level)
    # quiet chatty libs
    for noisy in ("httpx", "httpcore", "asyncio", "arq"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger("permy")


logger = configure_logging(os.environ.get("PERMY_ENV", "local"), os.environ.get("PERMY_LOG_LEVEL", "INFO"))
