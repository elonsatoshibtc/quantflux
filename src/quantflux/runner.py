"""QuantFlux end-to-end paper-trading runner.

Wires the six layers together:
    market_data -> signal_router -> risk.guard -> execution.paper_broker
    with charting + structured logging on the side.

Run:  python -m quantflux.runner --iterations 500
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
from quantflux.utils.logging_setup import log_event, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantFlux paper-trading runner")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    cfg = load_config()
    logger = setup_logging(cfg.log_dir)
    log_event(logger, "startup", event="startup", meta={"mode": cfg.execution.mode.value})

    feed = SyntheticFeed(cfg.market_data, seed=args.seed)
    broker = PaperBroker(cfg.execution)
    guard = RiskGuard(cfg.risk, broker)
    charting = ChartingFeed(cfg.charting)
    rng = random.Random(args.seed)
    processed = {"accepted": 0, "rejected": 0, "signals": 0}

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
    router.cfg.hmac_secret  # noqa: B018 (documented fixed secret in paper mode)

    for i in range(args.iterations):
        for sym in cfg.market_data.symbols:
            tick: Tick = feed.next_tick(sym)
            broker.mark(tick)
            charting.ingest(tick)
            if rng.random() < 0.05:  # ~5% chance of an inbound webhook signal
                _inject_signed_signal(router, cfg, tick, rng, i)

    equity = broker.equity()
    log_event(logger, "shutdown", event="shutdown",
              meta={"equity": round(equity, 2), **processed})
    _safe_print(charting.render())
    print(json.dumps({
        "equity": round(equity, 2),
        "fills": len(broker.fills),
        "signals": processed["signals"],
        "accepted": processed["accepted"],
        "rejected": processed["rejected"],
        "kill_switch": guard.killed,
    }, indent=2))
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
