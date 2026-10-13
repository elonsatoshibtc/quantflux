"""Shared helpers for the autonomous build/test/monitor loops.

These scripts are meant to be driven by OpenClaw `automations` on a schedule,
NOT by infinite `sleep`/`poll` loops in a shell. Each invocation does one
bounded unit of work and writes a structured line to the loop ledger.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "logs" / "loop_ledger.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_ledger(kind: str, status: str, detail: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), "loop": kind, "status": status, "detail": detail}
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def run(cmd: list[str]) -> tuple[int, str]:
    """Run a command in the repo root, capture combined output."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=900,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def python() -> str:
    return sys.executable or "python"
