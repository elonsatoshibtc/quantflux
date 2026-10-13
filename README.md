# QuantFlux

**Autonomous algorithmic trading execution terminal — SIMULATION / PAPER ONLY.**

QuantFlux monitors real-time-style market data, routes inbound webhook signals
through an authenticated DEX signal router, applies strict risk controls, and
executes against a simulated paper broker. It is built for **research, strategy
development, and dry runs** — it is intentionally incapable of touching real
capital.

> ⚠️ **No live keys. No real orders. Ever.**
> The configuration layer hard-fails at startup if live-exchange credential
> environment variables are present. There is no live broker class in the code.

---

## Architecture

```
                 +-------------------+        +----------------------+
 synthetic/REST  |  market_data      |        |  signal_router       |
 price feed ---->|  feed.py          |---+--->|  router.py           |
                 |  (Tick stream)    |   |    |  HMAC + replay guard |
                 +-------------------+   |    +----------+-----------+
                          |              |               |
                          v              |               v
                 +-------------------+   |    +----------------------+
   charting <----|  charting.feed    |   |    |  risk.guard          |
   sparklines     |  ring buffers     |   |    |  caps + kill-switch  |
                 +-------------------+   |    +----------+-----------+
                                         |               |
                                         v               v
                                +---------------------------------+
                                |  execution.paper_broker         |
                                |  simulated fills, fees, slippage|
                                +---------------------------------+
                                         |
                                         v
                                structured JSONL logs -> logs/
```

### Layers

| Layer | Module | Responsibility |
|---|---|---|
| Market data | `market_data/feed.py` | Deterministic synthetic feed (default) or read-only public REST. Emits `Tick`s. |
| Signal router | `signal_router/router.py` | HMAC-SHA256 authenticated inbound webhook signals, timestamp skew + nonce replay defense. |
| Execution | `execution/paper_broker.py` | `PaperBroker` — simulated fills with fees and slippage. No live class exists. |
| Risk | `risk/guard.py` | Per-asset & gross exposure caps, order-rate throttle, daily-loss **kill-switch**. |
| Charting | `charting/feed.py` | Bounded ring buffers + terminal sparklines; compact series for a browser feed. |
| Config | `config/settings.py` | Frozen dataclass config; refuses live mode / live credentials. |

---

## Quickstart

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest -q                                          # run tests
python -m quantflux.runner --iterations 300        # run a paper session
```

Example output:

```
  BTC/USDT   63012.44  ▃▄▅▄▆▅▇▆▅▄▅▆▇█▇▆▅▄▃▄▅▆▇▆▅
  ETH/USDT    3104.10  ▄▅▆▅▇▆▅▄▃▄▅▆▇█▇▆▅▄▅▆▇▆▅▄▃▄
  SOL/USDT     145.02  ▅▆▇▆▅▄▃▄▅▆▇█▇▆▅▄▅▆▇▆▅▄▃▄▅▆
{
  "equity": 10000.0,
  "fills": 12,
  "signals": 42,
  "accepted": 12,
  "rejected": 30,
  "kill_switch": false
}
```

---

## Signal webhook contract

`SignalRouter.handle(headers, body)` is transport-agnostic (easy to test). A
valid signal must include:

| Header | Meaning |
|---|---|
| `X-QF-Timestamp` | Unix seconds; must be within `max_clock_skew_seconds` (30) |
| `X-QF-Signature` | `HMAC-SHA256(secret, "<timestamp>." + raw_body)` hex digest |

Body:

```json
{ "ts": "...", "symbol": "BTC/USDT", "side": "buy",
  "qty": 0.01, "price": null, "nonce": "unique-id", "reason": "webhook" }
```

Replayed nonces (within the replay window) are rejected with `409`.

---

## Risk model

- `max_position_pct` — per-asset notional cap (default 20%)
- `max_gross_exposure_pct` — total notional cap (default 60%)
- `max_daily_loss_pct` — trips the **kill-switch** and halts order flow (default 5%)
- `max_orders_per_minute` — rolling 60s order throttle (default 30)
- Kill-switch **latches** until manually reset (`RiskGuard.reset()`), mirroring real practice.

---

## Autonomous loops

Three bounded loops are provided under `scripts/` and are meant to be driven by
OpenClaw `automations` on a schedule (not by shell `sleep` loops):

| Loop | Script | Cadence | Purpose |
|---|---|---|---|
| Build | `scripts/loop_build.py` | every 30 min | ruff + pytest; record pass/fail |
| Sim | `scripts/loop_sim.py` | every 15 min | run a bounded paper session; record KPIs |
| Audit | `scripts/loop_audit.py` | hourly | summarize ledger, write `logs/audit_<date>.md` |

Each writes one JSON line to `logs/loop_ledger.jsonl`.

---

## Safety guarantees

1. `config.settings._assert_no_live_credentials()` refuses to start if any live key env var is set.
2. `PaperBroker` raises if constructed in a non-simulation mode.
3. `TradingMode` has no `LIVE` member.
4. Webhook auth is mandatory (HMAC) with replay + clock-skew defense.
5. Kill-switch latches on daily loss or manual trigger.

## License

MIT (see repository). Simulation software — not investment advice.
