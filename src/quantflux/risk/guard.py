"""Risk guard and kill-switch.

Every order must pass `RiskGuard.check()` before the broker sees it. The guard
enforces per-asset and gross exposure caps, a rolling order-rate limit, and a
daily-loss kill-switch. Once the kill-switch latches it must be reset manually,
which mirrors real trading safety practice.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from quantflux.config.settings import RiskConfig
from quantflux.execution.paper_broker import PaperBroker


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = "ok"


class RiskGuard:
    def __init__(self, cfg: RiskConfig, broker: PaperBroker) -> None:
        self.cfg = cfg
        self.broker = broker
        self._order_times: deque[float] = deque()
        self._day_start_equity: float = broker.equity()
        self._killed = False
        self._kill_reason = ""

    # -- kill-switch -------------------------------------------------------
    @property
    def killed(self) -> bool:
        return self._killed

    def kill(self, reason: str) -> None:
        if self.cfg.kill_switch_enabled:
            self._killed = True
            self._kill_reason = reason

    def reset(self) -> None:
        """Manual reset after human review."""
        self._killed = False
        self._kill_reason = ""
        self._day_start_equity = self.broker.equity()

    def _check_daily_loss(self) -> None:
        eq = self.broker.equity()
        if self._day_start_equity <= 0:
            return
        drawdown = (self._day_start_equity - eq) / self._day_start_equity
        if drawdown >= self.cfg.max_daily_loss_pct:
            self.kill(f"daily_loss_limit:{drawdown:.4f}")

    # -- rate limiting -----------------------------------------------------
    def _check_rate(self) -> bool:
        now = time.time()
        while self._order_times and now - self._order_times[0] > 60:
            self._order_times.popleft()
        return len(self._order_times) < self.cfg.max_orders_per_minute

    def check(self, symbol: str, side: str, qty: float, ref_px: float) -> RiskDecision:
        self._check_daily_loss()
        if self._killed:
            return RiskDecision(False, f"kill_switch:{self._kill_reason}")

        if not self._check_rate():
            return RiskDecision(False, "rate_limit_exceeded")

        equity = self.broker.equity()
        if equity <= 0:
            return RiskDecision(False, "no_equity")

        new_notional = qty * ref_px
        pos = self.broker.portfolio.positions.get(symbol)
        cur_notional = pos.notional if pos else 0.0
        if (cur_notional + new_notional) / equity > self.cfg.max_position_pct:
            return RiskDecision(False, "max_position_pct")

        gross = sum(p.notional for p in self.broker.portfolio.positions.values())
        if (gross + new_notional) / equity > self.cfg.max_gross_exposure_pct:
            return RiskDecision(False, "max_gross_exposure_pct")

        self._order_times.append(time.time())
        return RiskDecision(True)
