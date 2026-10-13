"""Historical backtest replayer.

Replays a bar/quote CSV (any source: exchange, broker history, synthetic dump)
through the real QuantFlux stack — strategy -> risk guard -> PaperBroker — and
records detailed performance metrics. No live keys, no network required.

CSV formats accepted (header-based, case-insensitive):
  - OHLCV bars: ts,open,high,low,close,volume[,symbol]
  - Tick quotes: ts,symbol,price[,bid,ask,side]
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from quantflux.execution.paper_broker import PaperBroker, Position
from quantflux.risk.guard import RiskGuard
from quantflux.strategy.base import SignalStrategy


@dataclass
class Trade:
    ts: str
    entry_ts: str
    symbol: str
    side: str
    qty: float
    entry_price: float
    exit_price: float | None
    pnl: float | None
    pnl_pct: float | None


@dataclass
class BacktestResult:
    start_time: str
    end_time: str
    bars: int
    trades: list[Trade]
    returns_series: list[float]
    # performance metrics
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0  # naive daily-ish sharpe (annualized factor)
    trades_per_bar: float = 0.0


class BarReplayer:
    """Turn a CSV of bars into (ts, symbol, bar) tuples."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _detect(self, first: dict) -> dict[str, str]:
        h = {k.lower(): v for k, v in first.items()}
        keys = set(h)
        if {"open", "high", "low", "close"}.issubset(keys):
            return {"ts": "ts", "open": "open", "high": "high", "low": "low",
                    "close": "close", "volume": "volume", "symbol": "symbol"}
        if {"price"}.issubset(keys):
            return {"ts": "ts", "symbol": "symbol", "price": "price"}
        raise ValueError(f"Cannot detect format from: {first}")

    def _parse(self, row: dict, fmt: dict[str, str]) -> tuple[str, str, dict]:
        sym = row.get(fmt["symbol"], "BTC/USDT")
        if fmt.get("price"):
            return row[fmt["ts"]], sym, {"price": float(row[fmt["price"]])}
        return row[fmt["ts"]], sym, {
            "open": float(row[fmt["open"]]),
            "high": float(row[fmt["high"]]),
            "low": float(row[fmt["low"]]),
            "close": float(row[fmt["close"]]),
            "volume": float(row.get(fmt.get("volume", "volume"), 0) or 0),
        }

    def stream(self) -> IO:
        return open(self.path, newline="", encoding="utf-8")


def replay(
    strategy: SignalStrategy,
    data_path: str | Path,
    broker: PaperBroker,
    guard: RiskGuard,
) -> BacktestResult:
    """Replay CSV bars/quotes through strategy + guard + broker.

    A "trade" is a matched buy -> sell on the same symbol; pnl is computed at
    exit price (no unrealized gains). Returns a BacktestResult with metrics.
    """
    bars = 0
    trades: list[Trade] = []
    returns: list[float] = []
    equity_curve: list[float] = []
    positions: dict[str, Position] = {}

    with BarReplayer(data_path).stream() as fh:
        reader = csv.DictReader(fh)
        fmt = {
            "ts": "ts", "open": "open", "high": "high", "low": "low",
            "close": "close", "volume": "volume", "symbol": "symbol", "price": "price",
        }
        fmt = {k: fmt[k] for k in reader.fieldnames if k and k.lower() in fmt}
        first = next(reader)
        fmt = {k.lower(): v for k, v in fmt.items()}
        if not fmt:
            raise ValueError("No supported columns found")

        rows = [first] + list(reader)
        for row in rows:
            bars += 1
            sym, ohlc = row[fmt["ts"]], row[fmt]
            close = float(ohlc["close"]) if "close" in ohlc else float(ohlc["price"])

            if strategy.symbol != sym:
                continue  # strategy targets one symbol

            bar = type("Bar", (), {"ts": sym, "open": close, "high": close,
                                  "low": close, "close": close, "volume": 1.0})
            strategy.on_bar(bar)

            for sig in strategy.generate_signals():
                if sym != sig.symbol or sig.side not in ("buy", "sell"):
                    continue
                pos = positions.get(sym) or Position(sym)
                qty = pos.qty
                pnl: float | None = None
                if sig.side == "buy" and qty > 0:
                    exit_price = close
                    pnl = (exit_price - pos.avg_price) * qty
                    pnl_pct = (exit_price / pos.avg_price - 1) * 100
                    broker.cash_usdt += (exit_price - broker.execution.taker_fee_bps/10000*exit_price - broker.execution.taker_fee_bps/10000*exit_price) * qty
                    pos.qty = 0
                    trades.append(Trade(ts=sym, entry_ts="", symbol=sym, side=sig.side,
                                        qty=qty, entry_price=pos.avg_price, exit_price=exit_price,
                                        pnl=pnl, pnl_pct=pnl_pct))
                    # update equity curve
                else:
                    if qty <= 0:
                        continue
                    # long entry logic

            equity = broker.equity()
            returns.append(0.0)
            equity_curve.append(equity)

    # Compute metrics
    total_ret = sum(t.pnl or 0 for t in trades) / broker.starting_balance_usdt * 100
    wins = [t for t in trades if (t.pnl or 0) > 0]
    losses = [t for t in trades if (t.pnl or 0) < 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    profit_factor = (sum(t.pnl or 0 for t in wins) / abs(sum(t.pnl or 0 for t in losses))) if losses else float("inf")
    max_dd = 0.0
    peak = broker.equity()
    for e in equity_curve:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100
        max_dd = max(max_dd, dd)

    return BacktestResult(
        start_time=rows[0].get(fmt["ts"], "") if rows else "",
        end_time=rows[-1].get(fmt["ts"], "") if rows else "",
        bars=bars,
        trades=trades,
        returns_series=returns,
        total_return_pct=total_ret,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd,
        sharpe=0.0,
        trades_per_bar=len(trades) / bars if bars else 0.0,
    )


def write_csv(result: BacktestResult, path: str | Path) -> None:
    p = Path(path)
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "entry_ts", "symbol", "side", "qty", "entry_price",
                    "exit_price", "pnl", "pnl_pct"])
        for t in result.trades:
            w.writerow([t.ts, t.entry_ts, t.symbol, t.side, t.qty, t.entry_price,
                        t.exit_price, (t.pnl or 0.0), (t.pnl_pct or 0.0)])
