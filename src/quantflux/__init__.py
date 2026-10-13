"""QuantFlux — autonomous algorithmic trading SIMULATION terminal (paper only).

Package entry points are re-exported here for convenience.
"""

from quantflux.charting.feed import ChartingFeed
from quantflux.config.settings import AppConfig, TradingMode, load_config
from quantflux.execution.paper_broker import Fill, PaperBroker, Portfolio
from quantflux.market_data.feed import SyntheticFeed, Tick, stream_ticks
from quantflux.risk.guard import RiskDecision, RiskGuard
from quantflux.signal_router.router import Signal, SignalRouter, compute_signature

__version__ = "0.1.0"

__all__ = [
    "AppConfig",
    "ChartingFeed",
    "Fill",
    "PaperBroker",
    "Portfolio",
    "RiskDecision",
    "RiskGuard",
    "Signal",
    "SignalRouter",
    "SyntheticFeed",
    "Tick",
    "TradingMode",
    "__version__",
    "compute_signature",
    "load_config",
    "stream_ticks",
]
