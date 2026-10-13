"""Base classes for QuantFlux trading strategies.

Strategies are stateful signal generators that consume a Tick stream and
produce Signals. They must never talk to the broker directly: orders flow
strategy -> Signal -> router -> risk guard -> broker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass

from quantflux.market_data.feed import Tick
from quantflux.signal_router.router import Signal


@dataclass
class Bar:
    """OHLCV bar for strategy state."""

    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class SignalStrategy(ABC):
    """Abstract base for all trading strategies.

    The strategy lifecycle:
        on_bar(bar)       -> state update, may emit signals
        on_tick(tick)     -> optional per-tick event (calls on_bar by default)

    Every strategy must implement `generate_signals`.
    """

    def __init__(self, name: str = "") -> None:
        self.name = name or self.__class__.__name__
        self.signals_emitted = 0
        self.bars_consumed = 0

    @abstractmethod
    def generate_signals(self) -> list[Signal]:
        """Produce a list of outbound Signals from current state."""

    def on_bar(self, bar: Bar) -> None:
        """Called per symbol per bar; forwards to strategy hooks."""

    def on_tick(self, tick: Tick) -> None:
        """Called per tick; default builds a bar from consecutive OHLC."""
        self._on_bar_from_tick(tick)

    def _on_bar_from_tick(self, tick: Tick) -> None:
        """Minimal default bar builder (close-based, no OHLC separation)."""
        bar = Bar(
            ts=tick.ts,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=1.0,
        )
        self.bars_consumed += 1
        self.on_bar(bar)

    def reset(self) -> None:
        self.signals_emitted = 0
        self.bars_consumed = 0


class DualMovingAverageStrategy(SignalStrategy):
    """Classic EMA cross strategy: buy when fast crosses above slow; sell otherwise.

    Configured via ema_fast_period, ema_slow_period, symbol, side, qty and
    a min_bar_warmup so EMAs are computed over a stable window.
    """

    def __init__(
        self,
        symbol: str,
        side: str,
        qty: float,
        ema_fast_period: int = 8,
        ema_slow_period: int = 21,
        min_bars: int = 50,
        reason: str = "ema_cross",
    ) -> None:
        super().__init__(f"ema_{ema_fast_period}_{ema_slow_period}_{symbol}")
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.fast_p = ema_fast_period
        self.slow_p = ema_slow_period
        self.min_bars = min_bars
        self.reason = reason
        self._closes: deque[float] = deque()
        self._fast_ema: float | None = None
        self._slow_ema: float | None = None
        self._prev_diff: float | None = None
        self._last_cross: str | None = None
        self._last_cross_bar: int = -1
        self._crosses = 0

    @property
    def fast_ema(self) -> float | None:
        return self._fast_ema

    @property
    def slow_ema(self) -> float | None:
        return self._slow_ema

    @property
    def last_cross(self) -> str | None:
        return self._last_cross

    @property
    def crosses(self) -> int:
        return self._crosses

    def _ema(self, values: list[float], period: int) -> float | None:
        """Simplified EMA over the last `period` values."""
        if len(values) < period:
            return None
        alpha = 2.0 / (period + 1)
        v = values[-period]
        for x in values[-period + 1 :]:
            v = x * alpha + v * (1 - alpha)
        return v

    def on_bar(self, bar: Bar) -> None:
        self.bars_consumed += 1
        self._closes.append(bar.close)
        fast, slow = (
            self._ema(list(self._closes), self.fast_p),
            self._ema(list(self._closes), self.slow_p),
        )
        self._fast_ema, self._slow_ema = fast, slow
        diff = fast - slow if (fast is not None and slow is not None) else 0.0

        if fast is not None and slow is not None and self.bars_consumed >= self.min_bars:
            if self._prev_diff is None:
                # first time we have both EMAs
                self._prev_diff = diff
            elif diff != 0 and (self._prev_diff == 0 or self._prev_diff * diff < 0):
                # sign change from flat or previous direction
                self._crosses += 1
                self._last_cross = "up" if diff > 0 else "down"
                self._prev_diff = diff
            elif diff != 0:
                # just update prev_diff if diff is non-zero
                self._prev_diff = diff
        elif fast is not None and slow is not None and self._prev_diff is None:
            self._prev_diff = diff

    def generate_signals(self) -> list[Signal]:
        signals: list[Signal] = []
        if self._fast_ema is None or self._slow_ema is None:
            return signals
        if self.last_cross == "up":
            signals.append(
                Signal(
                    ts="",
                    symbol=self.symbol,
                    side="buy",
                    qty=self.qty,
                    price=None,
                    nonce="",
                    reason=f"{self.reason}_bullish_cross_{self._crosses}",
                )
            )
        elif self.last_cross == "down":
            signals.append(
                Signal(
                    ts="",
                    symbol=self.symbol,
                    side="sell",
                    qty=self.qty,
                    price=None,
                    nonce="",
                    reason=f"{self.reason}_bearish_cross_{self._crosses}",
                )
            )
        self.signals_emitted += len(signals)
        return signals

    def reset(self) -> None:
        super().reset()
        self._closes.clear()
        self._fast_ema = None
        self._slow_ema = None
        self._prev_diff = None
        self._last_cross = None
        self._crosses = 0
