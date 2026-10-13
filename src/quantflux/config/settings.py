"""Central configuration for QuantFlux.

SIMULATION-ONLY BY DESIGN.
This module hard-fails if any live-trading configuration is detected.
There are no live API key slots. Do not add them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class TradingMode(str, Enum):
    """Execution mode. PAPER is the only permitted value in this codebase."""

    PAPER = "paper"
    SIMULATION = "simulation"


# Guard: refuse to run if someone tries to smuggle a live mode via env.
_FORBIDDEN_ENV_KEYS = (
    "QF_LIVE_API_KEY",
    "QF_LIVE_SECRET",
    "BINANCE_API_KEY",
    "BINANCE_SECRET_KEY",
)


def _assert_no_live_credentials() -> None:
    present = [k for k in _FORBIDDEN_ENV_KEYS if os.environ.get(k)]
    if present:
        raise RuntimeError(
            "QuantFlux is simulation-only. Refusing to start because live "
            f"credential environment variables are present: {present}. "
            "Remove them; this project must never touch real capital."
        )


@dataclass(frozen=True)
class MarketDataConfig:
    symbols: tuple[str, ...] = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    poll_interval_seconds: float = 2.0
    source: str = "synthetic"  # synthetic | public-rest (read-only, no keys)


@dataclass(frozen=True)
class SignalRouterConfig:
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8787
    # HMAC secret is REQUIRED for any webhook to be accepted. Generated per
    # run in paper mode if not supplied; never a live-trading credential.
    hmac_secret: str = "paper-mode-shared-secret"
    max_clock_skew_seconds: int = 30
    replay_window_seconds: int = 120


@dataclass(frozen=True)
class ExecutionConfig:
    mode: TradingMode = TradingMode.PAPER
    starting_balance_usdt: float = 10_000.0
    taker_fee_bps: float = 10.0
    slippage_bps: float = 5.0
    fill_model: str = "next-tick"  # next-tick | mid | pessimistic


@dataclass(frozen=True)
class RiskConfig:
    max_position_pct: float = 0.20        # per-asset exposure cap
    max_gross_exposure_pct: float = 0.60  # total notional cap
    max_daily_loss_pct: float = 0.05      # triggers kill-switch
    max_orders_per_minute: int = 30       # rate throttle
    kill_switch_enabled: bool = True


@dataclass(frozen=True)
class ChartingConfig:
    enabled: bool = True
    max_points_per_symbol: int = 500
    emit_interval_seconds: float = 1.0


@dataclass(frozen=True)
class AppConfig:
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)
    signal_router: SignalRouterConfig = field(default_factory=SignalRouterConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    charting: ChartingConfig = field(default_factory=ChartingConfig)
    log_dir: str = "logs"

    def validate(self) -> None:
        _assert_no_live_credentials()
        if self.execution.mode not in (TradingMode.PAPER, TradingMode.SIMULATION):
            raise RuntimeError(f"Refusing non-simulation mode: {self.execution.mode}")


def load_config() -> AppConfig:
    _assert_no_live_credentials()
    cfg = AppConfig()
    cfg.validate()
    return cfg
