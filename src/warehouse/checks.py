"""
Run the star schema checks in config/model_checks.yaml against Athena.

Each check is a SQL query that returns one number, "failures":
  error checks must return 0 (otherwise the models are broken)
  warn checks are known business gaps; we compare them with the number we expect

Used by scripts/check_models.py (laptop) and lambda/models_handler.py (Step Functions).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from src.athena_tools import fetch_rows, run_query

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKS_FILE = REPO_ROOT / "config" / "model_checks.yaml"
GOOD_RESULTS = ("PASS", "KNOWN")


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


def run_all(athena, checks: list[dict] | None = None, workers: int = 5) -> list[dict]:
    """Run every check, 5 at a time. Returns one plain dict per check (JSON friendly)."""
    checks = load_checks() if checks is None else checks
    with ThreadPoolExecutor(max_workers=workers) as pool:
        raw = list(pool.map(lambda c: run_check(athena, c), checks))
    return [
        {"name": check["name"], "severity": check["severity"], "failures": failures,
         "expect": check.get("expect"), "result": result}
        for check, failures, result in raw
    ]


def broken(results: list[dict]) -> list[dict]:
    """Checks that are not as expected (FAIL, CHANGED or ERROR)."""
    return [r for r in results if r["result"] not in GOOD_RESULTS]
