"""Test suite for QuantFlux (pytest). Pure-python, no network, no keys."""

from __future__ import annotations

import json
import time

import pytest

from quantflux.config.settings import TradingMode, load_config
from quantflux.execution.paper_broker import PaperBroker
from quantflux.market_data.feed import SyntheticFeed, Tick
from quantflux.risk.guard import RiskGuard
from quantflux.signal_router.router import (
    SignalRouter,
    compute_signature,
)


@pytest.fixture
def cfg():
    return load_config()


def _tick(symbol="BTC/USDT", price=63000.0) -> Tick:
    return Tick(ts="2026-01-01T00:00:00Z", symbol=symbol, price=price,
                bid=price - 1, ask=price + 1, source="test")


def test_config_is_simulation_only(cfg):
    assert cfg.execution.mode in (TradingMode.PAPER, TradingMode.SIMULATION)


def test_paper_broker_buy_and_sell(cfg):
    b = PaperBroker(cfg.execution)
    b.mark(_tick(price=63000.0))
    fill = b.submit("BTC/USDT", "buy", 0.01)
    assert fill is not None and fill.side == "buy"
    assert b.portfolio.positions["BTC/USDT"].qty == pytest.approx(0.01)
    sell = b.submit("BTC/USDT", "sell", 0.01)
    assert sell is not None
    assert b.portfolio.positions["BTC/USDT"].qty == pytest.approx(0.0)


def test_paper_broker_rejects_overspend(cfg):
    b = PaperBroker(cfg.execution)
    b.mark(_tick(price=63000.0))
    assert b.submit("BTC/USDT", "buy", 1000.0) is None


def test_risk_guard_blocks_oversized_position(cfg):
    b = PaperBroker(cfg.execution)
    b.mark(_tick(price=63000.0))
    g = RiskGuard(cfg.risk, b)
    # 1 BTC ~ 63000 >> 20% of 10000 equity
    assert not g.check("BTC/USDT", "buy", 1.0, 63000.0).allowed


def test_risk_guard_allows_small_position(cfg):
    b = PaperBroker(cfg.execution)
    b.mark(_tick(price=63000.0))
    g = RiskGuard(cfg.risk, b)
    assert g.check("BTC/USDT", "buy", 0.001, 63000.0).allowed


def test_kill_switch_latches(cfg):
    b = PaperBroker(cfg.execution)
    b.mark(_tick(price=63000.0))
    g = RiskGuard(cfg.risk, b)
    g.kill("manual_test")
    assert not g.check("BTC/USDT", "buy", 0.001, 63000.0).allowed
    g.reset()
    assert g.check("BTC/USDT", "buy", 0.001, 63000.0).allowed


def test_signature_roundtrip(cfg):
    body = b'{"a":1}'
    ts = str(time.time())
    sig = compute_signature(cfg.signal_router.hmac_secret, ts, body)
    router = SignalRouter(cfg.signal_router, lambda s: None)
    code, reason = router.handle({"X-QF-Signature": sig, "X-QF-Timestamp": ts}, body)
    # signature passes auth; body is valid JSON but lacks required fields -> 400
    assert code == 400
    assert reason == "missing_nonce"


def test_signature_rejects_bad_hmac(cfg):
    body = b'{"a":1}'
    ts = str(time.time())
    router = SignalRouter(cfg.signal_router, lambda s: None)
    code, reason = router.handle({"X-QF-Signature": "deadbeef", "X-QF-Timestamp": ts}, body)
    assert code == 401 and reason == "bad_signature"


def test_replay_is_blocked(cfg):
    seen = []
    router = SignalRouter(cfg.signal_router, seen.append)
    body = json.dumps({
        "ts": "2026-01-01T00:00:00Z", "symbol": "ETH/USDT", "side": "buy",
        "qty": 0.1, "price": None, "nonce": "fixed-nonce",
    }).encode()
    ts = str(time.time())
    sig = compute_signature(cfg.signal_router.hmac_secret, ts, body)
    h = {"X-QF-Signature": sig, "X-QF-Timestamp": ts}
    assert router.handle(h, body)[0] == 202
    assert router.handle(h, body)[0] == 409  # replay
    assert len(seen) == 1


def test_stale_timestamp_rejected(cfg):
    body = b'{"nonce":"x"}'
    old = str(time.time() - 3600)
    sig = compute_signature(cfg.signal_router.hmac_secret, old, body)
    router = SignalRouter(cfg.signal_router, lambda s: None)
    code, reason = router.handle({"X-QF-Signature": sig, "X-QF-Timestamp": old}, body)
    assert code == 401 and reason == "timestamp_out_of_window"


def test_feed_is_deterministic():
    a = SyntheticFeed(load_config().market_data, seed=42)
    b = SyntheticFeed(load_config().market_data, seed=42)
    assert a.next_tick("BTC/USDT").price == b.next_tick("BTC/USDT").price
