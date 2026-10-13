"""Lightweight charting feed.

Maintains a bounded ring buffer of recent prices per symbol and emits compact
records suitable for a browser or CLI sparkline. No heavyweight chart deps.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from quantflux.config.settings import ChartingConfig
from quantflux.market_data.feed import Tick


@dataclass
class ChartPoint:
    ts: str
    price: float


class ChartingFeed:
    def __init__(self, cfg: ChartingConfig) -> None:
        self.cfg = cfg
        self._series: dict[str, deque[ChartPoint]] = {}

    def ingest(self, tick: Tick) -> None:
        if not self.cfg.enabled:
            return
        dq = self._series.setdefault(tick.symbol, deque(maxlen=self.cfg.max_points_per_symbol))
        dq.append(ChartPoint(ts=tick.ts, price=tick.price))

    def snapshot(self) -> dict[str, list[float]]:
        return {sym: [p.price for p in pts] for sym, pts in self._series.items()}

    @staticmethod
    def sparkline(prices: list[float]) -> str:
        if not prices:
            return ""
        blocks = "▁▂▃▄▅▆▇█"
        lo, hi = min(prices), max(prices)
        rng = (hi - lo) or 1.0
        return "".join(blocks[int((p - lo) / rng * (len(blocks) - 1))] for p in prices)

    def render(self) -> str:
        lines = []
        for sym, prices in self.snapshot().items():
            last = prices[-1] if prices else float("nan")
            lines.append(f"{sym:>9} {last:>10.2f}  {self.sparkline(prices[-60:])}")
        return "\n".join(lines)
