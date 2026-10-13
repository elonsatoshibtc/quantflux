"""Exchange execution layer — PAPER / SIMULATION ONLY.

There is intentionally NO live-order class in this module. Orders are filled
against the in-memory simulated book using a configurable fill model. Any
attempt to instantiate a live broker raises immediately.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone

from quantflux.config.settings import ExecutionConfig, TradingMode
from quantflux.market_data.feed import Tick


@dataclass
class Fill:
    ts: str
    order_id: str
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    slippage: float


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.avg_price


@dataclass
class Portfolio:
    cash_usdt: float
    positions: dict[str, Position] = field(default_factory=dict)

    def exposure_pct(self) -> float:
        gross = sum(p.notional for p in self.positions.values())
        equity = self.cash_usdt + gross
        return 0.0 if equity <= 0 else gross / equity


class PaperBroker:
    """Simulated broker. The ONLY broker available in this project."""

    def __init__(self, cfg: ExecutionConfig) -> None:
        if cfg.mode not in (TradingMode.PAPER, TradingMode.SIMULATION):
            raise RuntimeError(
                f"PaperBroker refuses mode {cfg.mode!r}. Live trading is unsupported."
            )
        self.cfg = cfg
        self._ids = itertools.count(1)
        self.portfolio = Portfolio(cash_usdt=cfg.starting_balance_usdt)
        self.fills: list[Fill] = []
        self._last_px: dict[str, float] = {}

    def mark(self, tick: Tick) -> None:
        self._last_px[tick.symbol] = tick.price

    def _apply_slippage(self, side: str, ref_px: float) -> tuple[float, float]:
        slip = ref_px * (self.cfg.slippage_bps / 10_000.0)
        px = ref_px + slip if side == "buy" else ref_px - slip
        return px, slip

    def submit(self, symbol: str, side: str, qty: float, price: float | None = None) -> Fill | None:
        ref_px = price if price is not None else self._last_px.get(symbol)
        if ref_px is None:
            return None  # no market reference yet
        px, slip = self._apply_slippage(side, ref_px)
        notional = px * qty
        fee = notional * (self.cfg.taker_fee_bps / 10_000.0)

        # Cash/position accounting (long/flat only for the paper model).
        if side == "buy":
            if self.portfolio.cash_usdt < notional + fee:
                return None  # insufficient simulated cash
            self.portfolio.cash_usdt -= notional + fee
            pos = self.portfolio.positions.setdefault(symbol, Position(symbol))
            new_qty = pos.qty + qty
            pos.avg_price = (
                (pos.avg_price * pos.qty + px * qty) / new_qty if new_qty else 0.0
            )
            pos.qty = new_qty
        else:  # sell
            pos = self.portfolio.positions.get(symbol)
            if pos is None or pos.qty < qty:
                return None  # no shorting in paper model
            self.portfolio.cash_usdt += notional - fee
            pos.qty -= qty

        fill = Fill(
            ts=datetime.now(timezone.utc).isoformat(),
            order_id=f"paper-{next(self._ids)}",
            symbol=symbol,
            side=side,
            qty=qty,
            price=px,
            fee=fee,
            slippage=slip,
        )
        self.fills.append(fill)
        return fill

    def equity(self) -> float:
        gross = sum(
            abs(p.qty) * self._last_px.get(p.symbol, p.avg_price)
            for p in self.portfolio.positions.values()
        )
        return self.portfolio.cash_usdt + gross
