"""Loop 1 — BUILD: run lint + full test suite; record result to the ledger.

One bounded pass per invocation. Intended cadence: every 30 minutes.
Exit code 0 = green, 1 = failures.
"""

from __future__ import annotations

import _loop_common as c


def main() -> int:
    rc_lint, out_lint = c.run([c.python(), "-m", "ruff", "check", "src", "tests"])
    rc_test, out_test = c.run([c.python(), "-m", "pytest", "-q"])

    c.append_ledger("build", "pass" if rc_test == 0 else "fail", {
        "lint_rc": rc_lint,
        "test_rc": rc_test,
        "lint_tail": out_lint[-400:],
        "test_tail": out_test[-400:],
    })
    print(f"[build] lint_rc={rc_lint} test_rc={rc_test}")
    print(out_test[-800:])
    return 0 if rc_test == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
