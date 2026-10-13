"""Structured logging for QuantFlux.

Writes JSON-lines events to stdout and a rolling file under logs/.
Used by the continuous progress logger.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach structured extras when present.
        for key in ("event", "symbol", "side", "qty", "price", "reason", "meta"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger("quantflux")
    if root.handlers:
        return root
    root.setLevel(level)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(JsonLineFormatter())
    root.addHandler(stream)

    fh = logging.FileHandler(os.path.join(log_dir, "quantflux.jsonl"), encoding="utf-8")
    fh.setFormatter(JsonLineFormatter())
    root.addHandler(fh)
    return root


def log_event(logger: logging.Logger, msg: str, **fields: Any) -> None:
    """Emit a structured event; unknown fields land in `meta`."""
    known = {"event", "symbol", "side", "qty", "price", "reason"}
    extra = {k: v for k, v in fields.items() if k in known}
    meta = {k: v for k, v in fields.items() if k not in known}
    if meta:
        extra["meta"] = meta
    logger.info(msg, extra=extra)
