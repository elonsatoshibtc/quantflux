# Contributing

## Golden rule
**QuantFlux is simulation-only.** PRs that introduce live credential handling,
a live broker, or a `LIVE` trading mode will be rejected. This is non-negotiable.

## Workflow
1. Branch from `main`.
2. `pip install -e ".[dev]"`
3. Keep changes small and covered: `pytest -q` must stay green.
4. `ruff check src tests` should be clean.
5. Open a PR; CI runs lint, tests, and a 50-iteration smoke run.

## Style
- Type-hinted public functions.
- Frozen dataclasses for config.
- No network in unit tests; use the synthetic feed.
