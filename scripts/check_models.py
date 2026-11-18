"""
Run the star schema checks in config/model_checks.yaml against Athena.

Each check is a SQL query that returns one number, "failures":
  error checks must return 0 (otherwise the models are broken and the run fails)
  warn checks are known business gaps; we compare them with the number we expect

Checks run 5 at a time to save time. Each one scans only a few MB.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/check_models.py
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import athena_client, fetch_rows, run_query  # noqa: E402

CHECKS_FILE = REPO_ROOT / "config" / "model_checks.yaml"


def load_checks(path: Path = CHECKS_FILE) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["checks"]


def evaluate(check: dict, failures: int) -> str:
    """Turn a check's failure count into PASS, FAIL, KNOWN (expected gap) or CHANGED."""
    if check["severity"] == "error":
        return "PASS" if failures == 0 else "FAIL"
    return "KNOWN" if failures == check.get("expect", 0) else "CHANGED"


def run_check(athena, check: dict) -> tuple[dict, int | None, str]:
    try:
        execution_id = run_query(athena, check["sql"])
        failures = int(fetch_rows(athena, execution_id)[0]["failures"])
        return check, failures, evaluate(check, failures)
    except RuntimeError as err:
        return check, None, f"ERROR ({err})"


def main() -> None:
    athena = athena_client()
    checks = load_checks()

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda c: run_check(athena, c), checks))

    print(f"{'result':<9}{'failures':>9}  check")
    for check, failures, result in results:
        shown = "-" if failures is None else f"{failures:,}"
        note = f"  (expected {check['expect']:,})" if check["severity"] == "warn" else ""
        print(f"{result:<9}{shown:>9}  {check['name']}{note}")

    broken = [r for r in results if r[2] not in ("PASS", "KNOWN")]
    print(f"\n{len(results) - len(broken)} of {len(results)} checks as expected")
    if broken:
        sys.exit(f"{len(broken)} check(s) need attention")


if __name__ == "__main__":
    main()