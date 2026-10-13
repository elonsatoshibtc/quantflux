# QuantFlux architecture notes

## Design goals
1. **Simulation-only, structurally.** Safety is enforced in code, not policy:
   no `LIVE` enum member, no live broker class, startup guard against credential
   env vars.
2. **Transport-agnostic core.** `SignalRouter` and `PaperBroker` take plain
   data; the web server / scheduler are thin adapters, so everything is unit
   testable with no network.
3. **Bounded, observable loops.** Autonomous work happens in discrete passes
   that append to a ledger, so a scheduler (OpenClaw automations) can own
   cadence instead of a runaway daemon.

## Data flow
`SyntheticFeed -> Tick -> {broker.mark, charting.ingest}`
`webhook -> SignalRouter -> Signal -> RiskGuard.check -> PaperBroker.submit -> Fill -> log`

## Extension points
- **Real market data:** add a `PublicRestFeed` implementing `next_tick()` using
  keyless public endpoints. It must never accept credentials.
- **Backtesting:** swap `SyntheticFeed` for a historical replayer exposing the
  same `next_tick()` interface.
- **Strategies:** subscribe to `Tick`s and emit `Signal`s; a strategy never
  talks to the broker directly — it goes through the risk guard.

## Non-goals (explicit)
- Live order placement.
- Custody of funds or keys.
- Financial advice.
