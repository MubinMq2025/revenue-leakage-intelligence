"""
Run the star schema checks in config/model_checks.yaml against Athena.

The logic lives in src/warehouse/checks.py, shared with the "models" Lambda that
Step Functions runs every day. This script is the laptop entry point.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/check_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import athena_client  # noqa: E402
from src.warehouse.checks import CHECKS_FILE, broken, evaluate, load_checks, run_all, run_check  # noqa: E402,F401


def main() -> None:
    results = run_all(athena_client())

    print(f"{'result':<9}{'failures':>9}  check")
    for r in results:
        shown = "-" if r["failures"] is None else f"{r['failures']:,}"
        note = f"  (expected {r['expect']:,})" if r["severity"] == "warn" else ""
        print(f"{r['result']:<9}{shown:>9}  {r['name']}{note}")

    bad = broken(results)
    print(f"\n{len(results) - len(bad)} of {len(results)} checks as expected")
    if bad:
        sys.exit(f"{len(bad)} check(s) need attention")


if __name__ == "__main__":
    main()
