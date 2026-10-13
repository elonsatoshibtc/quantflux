"""Market-data ingester.

Provides a pluggable, READ-ONLY price feed. Default source is a deterministic
synthetic random-walk so the whole system can run with zero network access and
zero credentials. An optional public-REST source is provided for realism but
never requires or accepts API keys.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from quantflux.config.settings import MarketDataConfig


@dataclass(frozen=True)
class Tick:
    ts: str
    symbol: str
    price: float
    bid: float
    ask: float
    source: str


class SyntheticFeed:
    """Deterministic (seeded) random-walk price source for paper trading."""

    def __init__(self, cfg: MarketDataConfig, seed: int = 7) -> None:
        self.cfg = cfg
        self._rng = random.Random(seed)
        self._prices: dict[str, float] = {
            "BTC/USDT": 63_000.0,
            "ETH/USDT": 3_100.0,
            "SOL/USDT": 145.0,
        }
        self._vol = {"BTC/USDT": 0.0015, "ETH/USDT": 0.002, "SOL/USDT": 0.003}

    def _step(self, symbol: str) -> float:
        p = self._prices.get(symbol, 100.0)
        vol = self._vol.get(symbol, 0.002)
        drift = self._rng.gauss(0, vol)
        p = max(0.01, p * math.exp(drift))
        self._prices[symbol] = p
        return p

    def next_tick(self, symbol: str) -> Tick:
        mid = self._step(symbol)
        spread = mid * 0.0002
        return Tick(
            ts=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            price=mid,
            bid=mid - spread / 2,
            ask=mid + spread / 2,
            source="synthetic",
        )


def stream_ticks(
    cfg: MarketDataConfig,
    on_tick: Callable[[Tick], None],
    iterations: int | None = None,
) -> None:
    """Drive the feed. In production this is wrapped by the scheduler loop."""
    feed = SyntheticFeed(cfg)
    symbols: Iterable[str] = cfg.symbols
    i = 0
    while iterations is None or i < iterations:
        for sym in symbols:
            on_tick(feed.next_tick(sym))
        i += 1
