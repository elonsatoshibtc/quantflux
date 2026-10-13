"""Tests for the QuantFlux strategy module."""

from __future__ import annotations

from quantflux.signal_router.router import Signal
from quantflux.strategy.base import DualMovingAverageStrategy, SignalStrategy


class DummyStrategy(SignalStrategy):
    def __init__(self, emit_on: int = 1) -> None:
        super().__init__("dummy")
        self.emit_on = emit_on
        self.calls = 0

    def generate_signals(self) -> list[Signal]:
        self.calls += 1
        if self.calls >= self.emit_on:
            return [Signal(ts="", symbol="BTC/USDT", side="buy", qty=0.001,
                           price=None, nonce="", reason="test")]
        return []


def test_strategy_base() -> None:
    s = DummyStrategy(emit_on=2)
    assert s.name == "dummy"
    assert s.signals_emitted == 0
    assert s.bars_consumed == 0
    # on_tick builds a bar by default
    s.on_tick(type("Tick", (), {"ts": "2026-01-01", "symbol": "BTC/USDT",
                                "price": 100, "bid": 99.5, "ask": 100.5,
                                "source": "test"}))
    assert s.bars_consumed == 1
    # no signals yet (emit_on=2 not reached)
    assert s.generate_signals() == []
    assert s.signals_emitted == 0
    s.reset()
    assert s.signals_emitted == 0
    assert s.bars_consumed == 0


def test_dma_initial_state() -> None:
    strat = DualMovingAverageStrategy(symbol="ETH/USDT", side="buy", qty=0.01)
    assert strat.name == "ema_8_21_ETH/USDT"
    assert strat.symbol == "ETH/USDT"
    assert strat.fast_p == 8
    assert strat.slow_p == 21
    assert strat.min_bars == 50
    assert strat.fast_ema is None
    assert strat.slow_ema is None
    assert strat.last_cross is None
    assert strat.crosses == 0


def test_dma_ema_computation() -> None:
    strat = DualMovingAverageStrategy(symbol="BTC/USDT", side="buy", qty=0.01,
                                      ema_fast_period=2, ema_slow_period=3, min_bars=1)
    prices = [10.0, 11.0, 12.0, 11.0, 13.0]
    for p in prices:
        strat.on_bar(type("Bar", (), {"ts": "", "open": p, "high": p, "low": p,
                                      "close": p, "volume": 1.0}))
    # after 5 bars, EMAs should be computed
    assert strat.fast_ema is not None
    assert strat.slow_ema is not None
    assert isinstance(strat.fast_ema, float)
    assert isinstance(strat.slow_ema, float)
    # No cross yet — prices are monotonic-ish, no sign change
    assert strat.crosses == 0
    # Reset and verify clean state
    strat.reset()
    assert strat.fast_ema is None
    assert strat.slow_ema is None
    assert strat.signals_emitted == 0
    assert strat.bars_consumed == 0


def test_dma_cross_detection() -> None:
    strat = DualMovingAverageStrategy(symbol="BTC/USDT", side="buy", qty=0.01,
                                      ema_fast_period=2, ema_slow_period=3, min_bars=1)
    # Create a clear cross: start low, then jump high
    prices = [10.0, 10.0, 10.0, 20.0, 20.0]
    for i, p in enumerate(prices):
        strat.on_bar(type("Bar", (), {"ts": f"2026-01-01T00:00:{i:02d}", "open": p,
                                      "high": p, "low": p, "close": p, "volume": 1.0}))
    # After the cross, fast should be above slow
    assert strat.fast_ema is not None
    assert strat.slow_ema is not None
    assert strat.fast_ema > strat.slow_ema
    assert strat.last_cross == "up"
    assert strat.crosses == 1
    # Generate signals — should emit a buy
    signals = strat.generate_signals()
    assert len(signals) == 1
    sig = signals[0]
    assert sig.side == "buy"
    assert sig.symbol == "BTC/USDT"
    assert "bullish_cross_1" in sig.reason
    # Reset clears everything
    strat.reset()
    assert strat.fast_ema is None
    assert strat.slow_ema is None
    assert strat.last_cross is None
    assert strat.crosses == 0
    assert strat.signals_emitted == 0
    assert strat.bars_consumed == 0