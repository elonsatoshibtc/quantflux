"""QuantFlux end-to-end paper-trading runner.

Wires the layers together:
    market_data -> {signal_router | strategy} -> risk.guard -> execution.paper_broker
    with charting + structured logging on the side.

Two signal sources are supported:
  --strategy ema    drive orders from DualMovingAverageStrategy (default)
  --strategy random drive orders from the synthetic webhook injector

Run:  python -m quantflux.runner --iterations 1000 --strategy ema
This NEVER connects to a live exchange and NEVER uses API keys.
"""

from __future__ import annotations

import argparse
import json
import random

from quantflux.charting.feed import ChartingFeed
from quantflux.config.settings import load_config
from quantflux.execution.paper_broker import PaperBroker
from quantflux.market_data.feed import SyntheticFeed, Tick
from quantflux.risk.guard import RiskGuard
from quantflux.signal_router.router import Signal, SignalRouter, compute_signature
from quantflux.strategy.base import DualMovingAverageStrategy
from quantflux.utils.logging_setup import log_event, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantFlux paper-trading runner")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--strategy", choices=("ema", "random"), default="ema",
                        help="signal source: ema (DualMovingAverageStrategy) or random webhook injector")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--qty", type=float, default=0.001)
    parser.add_argument("--ema-fast", type=int, default=8)
    parser.add_argument("--ema-slow", type=int, default=21)
    parser.add_argument("--min-bars", type=int, default=30)
    args = parser.parse_args()

    cfg = load_config()
    logger = setup_logging(cfg.log_dir)
    log_event(logger, "startup", event="startup",
              meta={"mode": cfg.execution.mode.value, "strategy": args.strategy})

    feed = SyntheticFeed(cfg.market_data, seed=args.seed)
    broker = PaperBroker(cfg.execution)
    guard = RiskGuard(cfg.risk, broker)
    charting = ChartingFeed(cfg.charting)
    rng = random.Random(args.seed)
    processed = {"accepted": 0, "rejected": 0, "signals": 0}

    strategy = DualMovingAverageStrategy(
        symbol=args.symbol,
        side="buy",
        qty=args.qty,
        ema_fast_period=args.ema_fast,
        ema_slow_period=args.ema_slow,
        min_bars=args.min_bars,
    )

    def on_signal(sig: Signal) -> None:
        processed["signals"] += 1
        ref_px = sig.price or broker._last_px.get(sig.symbol, 0.0)
        decision = guard.check(sig.symbol, sig.side, sig.qty, ref_px)
        if not decision.allowed:
            processed["rejected"] += 1
            log_event(logger, "signal_rejected", event="signal_rejected",
                      symbol=sig.symbol, side=sig.side, reason=decision.reason)
            return
        fill = broker.submit(sig.symbol, sig.side, sig.qty, sig.price)
        if fill is None:
            processed["rejected"] += 1
            log_event(logger, "fill_skipped", event="fill_skipped", symbol=sig.symbol)
        else:
            processed["accepted"] += 1
            log_event(logger, "fill", event="fill", symbol=fill.symbol,
                      side=fill.side, qty=fill.qty, price=fill.price)

    router = SignalRouter(cfg.signal_router, on_signal)

    for i in range(args.iterations):
        for sym in cfg.market_data.symbols:
            tick: Tick = feed.next_tick(sym)
            broker.mark(tick)
            charting.ingest(tick)

            if args.strategy == "ema":
                if sym == strategy.symbol:
                    strategy.on_tick(tick)
                    for sig in strategy.generate_signals():
                        if sig.side not in ("buy", "sell"):
                            continue
                        on_signal(sig)
            else:
                if rng.random() < 0.05:  # ~5% chance of an inbound webhook signal
                    _inject_signed_signal(router, cfg, tick, rng, i)

    equity = broker.equity()
    result = {
        "equity": round(equity, 2),
        "return_pct": round((equity / cfg.execution.starting_balance_usdt - 1) * 100, 4),
        "fills": len(broker.fills),
        "signals": processed["signals"],
        "accepted": processed["accepted"],
        "rejected": processed["rejected"],
        "kill_switch": guard.killed,
        "strategy": args.strategy,
        "strategy_name": strategy.name if args.strategy == "ema" else "random_webhook",
        "bars": strategy.bars_consumed if args.strategy == "ema" else args.iterations,
        "crosses": strategy.crosses if args.strategy == "ema" else 0,
    }
    log_event(logger, "shutdown", event="shutdown", meta=result)
    _safe_print(charting.render())
    print(json.dumps(result, indent=2))
    return 0


def _safe_print(text: str) -> None:
    """Print text, degrading gracefully on consoles that lack Unicode support.

    Windows consoles (cp1252) cannot render the sparkline block glyphs. We try
    UTF-8 first, then fall back to an ASCII rendering instead of crashing.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        ascii_text = text.encode("ascii", "replace").decode("ascii")
        print(ascii_text)


def _inject_signed_signal(router: SignalRouter, cfg, tick: Tick, rng: random.Random, i: int) -> None:
    body = json.dumps({
        "ts": tick.ts,
        "symbol": tick.symbol,
        "side": rng.choice(["buy", "sell"]),
        "qty": round(rng.uniform(0.001, 0.02), 6),
        "price": None,
        "nonce": f"n{i}-{tick.symbol}",
        "reason": "synthetic_webhook",
    }).encode()
    import time
    ts = str(time.time())
    sig = compute_signature(cfg.signal_router.hmac_secret, ts, body)
    router.handle({"X-QF-Signature": sig, "X-QF-Timestamp": ts}, body)


if __name__ == "__main__":
    raise SystemExit(main())
