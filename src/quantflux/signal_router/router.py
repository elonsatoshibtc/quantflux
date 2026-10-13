"""DEX / webhook signal router.

Accepts inbound JSON signals at POST /signal, authenticates them with HMAC-SHA256
over the raw body, enforces a replay window, and forwards valid signals onto the
execution layer.

Security posture (deliberately strict):
  * HMAC signature REQUIRED (X-QF-Signature).
  * Timestamp REQUIRED (X-QF-Timestamp) within max_clock_skew_seconds.
  * A monotonic nonce cache prevents replay within the replay window.
  * Binds to 127.0.0.1 by default.
  * No endpoint ever accepts or uses a live exchange credential.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from quantflux.config.settings import SignalRouterConfig


@dataclass(frozen=True)
class Signal:
    ts: str
    symbol: str
    side: str      # buy | sell
    qty: float
    price: float | None
    nonce: str
    reason: str = "webhook"


class ReplayCache:
    def __init__(self, window_seconds: int) -> None:
        self.window = window_seconds
        self._seen: OrderedDict[str, float] = OrderedDict()

    def _evict(self, now: float) -> None:
        while self._seen:
            _, t = next(iter(self._seen.items()))
            if now - t > self.window:
                self._seen.popitem(last=False)
            else:
                break

    def check_and_add(self, nonce: str) -> bool:
        """Return True if fresh, False if replayed."""
        now = time.time()
        self._evict(now)
        if nonce in self._seen:
            return False
        self._seen[nonce] = now
        return True


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return mac.hexdigest()


def verify_signature(
    cfg: SignalRouterConfig,
    signature: str,
    timestamp: str,
    body: bytes,
) -> tuple[bool, str]:
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return False, "missing_or_invalid_timestamp"
    if abs(time.time() - ts) > cfg.max_clock_skew_seconds:
        return False, "timestamp_out_of_window"
    expected = compute_signature(cfg.hmac_secret, timestamp, body)
    if not hmac.compare_digest(expected, signature or ""):
        return False, "bad_signature"
    return True, "ok"


class SignalRouter:
    def __init__(self, cfg: SignalRouterConfig, on_signal: Callable[[Signal], None]) -> None:
        self.cfg = cfg
        self._on_signal = on_signal
        self._replay = ReplayCache(cfg.replay_window_seconds)

    def handle(self, headers: dict[str, str], body: bytes) -> tuple[int, str]:
        """Pure request handler. Transport-agnostic so it is easy to test."""
        ok, reason = verify_signature(
            self.cfg,
            headers.get("X-QF-Signature", ""),
            headers.get("X-QF-Timestamp", ""),
            body,
        )
        if not ok:
            return 401, reason
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return 400, "invalid_json"

        nonce = str(data.get("nonce", ""))
        if not nonce:
            return 400, "missing_nonce"
        if not self._replay.check_and_add(nonce):
            return 409, "replay_detected"

        try:
            sig = Signal(
                ts=str(data["ts"]),
                symbol=str(data["symbol"]),
                side=str(data["side"]).lower(),
                qty=float(data["qty"]),
                price=(float(data["price"]) if data.get("price") is not None else None),
                nonce=nonce,
                reason=str(data.get("reason", "webhook")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return 422, f"malformed_signal:{exc}"

        if sig.side not in ("buy", "sell") or sig.qty <= 0:
            return 422, "invalid_side_or_qty"

        self._on_signal(sig)
        return 202, "accepted"
