"""
Validate the Olist CSVs on your laptop, exactly as the Lambda will in AWS.

Each local file is treated as if it had arrived at
    raw/<table>/load_date=<today>/<file>.csv
so the outputs land in data/output/ with the same layout as S3:
    data/output/validated/<table>/load_date=.../<file>.csv
    data/output/quarantine/<table>/load_date=.../<file>_rejected.csv
    data/output/dq-reports/<table>/load_date=.../<file>_dq_report.json

Usage (from the repo root, with .venv active):
    python -m src.dq_platform.run_local                 # all 9 tables
    python -m src.dq_platform.run_local --table orders  # just one
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from src.dq_platform.outputs import build_report, output_keys
from src.dq_platform.rules import REPO_ROOT, load_contract
from src.dq_platform.tables import TABLE_FILES
from src.dq_platform.validator import validate

logging.basicConfig(level=logging.ERROR, format="%(levelname)s | %(message)s")
logger = logging.getLogger("run_local")

DEFAULT_DATA_DIR = REPO_ROOT / "data" / "olist"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "output"


def read_raw_csv(path: Path) -> pd.DataFrame:
    """Read every column as text so bad values are kept exactly as received."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def run_table(table: str, data_dir: Path, output_dir: Path, load_date: str) -> dict:
    file_name = TABLE_FILES[table]
    raw_key = f"raw/{table}/load_date={load_date}/{file_name}"

    rules = load_contract(table)
    result = validate(read_raw_csv(data_dir / file_name), rules)
    report = build_report(result, rules, raw_key)

    paths = {zone: output_dir / key for zone, key in output_keys(raw_key).items()}
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    result.valid.to_csv(paths["validated"], index=False)
    result.rejected.to_csv(paths["rejected"], index=False)
    paths["dq_report"].write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Olist CSVs locally.")
    parser.add_argument("--table", choices=sorted(TABLE_FILES), help="Validate one table (default: all)")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    tables = [args.table] if args.table else list(TABLE_FILES)
    load_date = date.today().isoformat()

    print(f"{'table':<22}{'status':<22}{'rows':>10}{'rejected':>10}{'flagged':>10}")
    for table in tables:
        r = run_table(table, args.data_dir, args.output_dir, load_date)
        print(f"{table:<22}{r['status']:<22}{r['total_rows']:>10,}{r['rejected_rows']:>10,}{r['flagged_rows']:>10,}")
        for w in r["warnings"]:
            print(f"    {w['rule_id']}: {w['message']}")
        for f in r["rule_failures"]:
            if f["severity"] == "reject" and f["failed_rows"]:
                print(f"    {f['rule_id']} (reject): {f['failed_rows']:,} rows failed {f['rule_name']}")

    print(f"\nOutputs written to {args.output_dir.relative_to(REPO_ROOT) if args.output_dir.is_relative_to(REPO_ROOT) else args.output_dir}")


if __name__ == "__main__":
    main()