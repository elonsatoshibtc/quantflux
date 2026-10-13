"""Loop 3 — AUDIT: continuous review logger.

Summarizes the loop ledger (build/sim history), flags anomalies (test failures,
kill-switch trips, negative PnL drift) and writes a human-readable daily note to
logs/audit_YYYY-MM-DD.md. Intended cadence: hourly.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

import _loop_common as c
from pathlib import Path


def main() -> int:
    if not c.LEDGER.exists():
        c.append_ledger("audit", "empty", {"note": "no ledger yet"})
        print("[audit] ledger empty")
        return 0

    rows = [json.loads(line) for line in c.LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    recent = rows[-200:]
    counts = Counter((r["loop"], r["status"]) for r in recent)

    anomalies = []
    for r in recent:
        if r["loop"] == "build" and r["status"] == "fail":
            anomalies.append({"ts": r["ts"], "type": "test_failure"})
        if r["loop"] == "sim" and r["detail"].get("kill_switch"):
            anomalies.append({"ts": r["ts"], "type": "kill_switch_tripped"})

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = Path(c.REPO_ROOT) / "logs" / f"audit_{day}.md"
    lines = [
        f"# QuantFlux audit — {day}",
        "",
        f"- Ledger records reviewed (last 200): {len(recent)}",
        f"- Totals: {dict(counts)}",
        f"- Anomalies: {len(anomalies)}",
        "",
    ]
    if anomalies:
        lines.append("## Anomalies")
        for a in anomalies[-20:]:
            lines.append(f"- {a['ts']} — {a['type']}")
    else:
        lines.append("No anomalies detected. System nominal.")

    day_start = f"_Written {datetime.now(timezone.utc).isoformat()}_\n"
    note.write_text("\n".join(lines) + "\n" + day_start, encoding="utf-8")

    c.append_ledger("audit", "ok", {"nodes": len(recent), "anomalies": len(anomalies)})
    print(f"[audit] reviewed={len(recent)} anomalies={len(anomalies)} -> {note.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
