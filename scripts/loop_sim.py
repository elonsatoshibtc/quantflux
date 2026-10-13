"""Loop 2 — SIM: run a bounded paper-trading session and record KPIs.

One bounded pass per invocation. Intended cadence: every 15 minutes.
Drives orders from DualMovingAverageStrategy (EMA cross) through the real
risk guard + paper broker. Simulation only; no network, no keys.
"""

from __future__ import annotations

import json
import _loop_common as c

ITERATIONS = "1000"


def main() -> int:
    rc, out = c.run([
        c.python(), "-m", "quantflux.runner",
        "--iterations", ITERATIONS,
        "--strategy", "ema",
    ])
    kpi: dict = {"rc": rc}
    # The runner prints a JSON summary block last; grab the trailing object.
    try:
        start = out.rindex("{")
        kpi.update(json.loads(out[start:]))
    except Exception:
        kpi["raw_tail"] = out[-600:]

    c.append_ledger("sim", "pass" if rc == 0 else "fail", kpi)
    print(f"[sim] {json.dumps(kpi)}")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
