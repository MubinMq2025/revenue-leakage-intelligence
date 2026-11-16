"""
Turn a ValidationResult into the three outputs the pipeline stores:

    validated/<table>/load_date=.../<file>.csv                 -> usable rows (with dq_flags)
    quarantine/<table>/load_date=.../<file>_rejected.csv       -> rejected rows + rejection_reasons
    dq-reports/<table>/load_date=.../<file>_dq_report.json     -> metrics for monitoring

The same functions are used locally and in AWS Lambda, so both write identical layouts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.dq_platform.tables import parse_raw_key
from src.dq_platform.validator import ValidationResult

ZONE_PREFIXES = {"validated": "validated/", "rejected": "quarantine/", "dq_reports": "dq-reports/"}


def output_keys(raw_key: str, prefixes: dict = ZONE_PREFIXES) -> dict:
    """Build the output paths for each zone, mirroring the raw table/partition layout."""
    parts = parse_raw_key(raw_key)
    base = f"{parts['table']}/{parts['partition']}"
    stem = parts["file"].removesuffix(".csv")
    return {
        "validated": f"{prefixes['validated']}{base}/{parts['file']}",
        "rejected": f"{prefixes['rejected']}{base}/{stem}_rejected.csv",
        "dq_report": f"{prefixes['dq_reports']}{base}/{stem}_dq_report.json",
    }


def build_report(result: ValidationResult, rules: dict, raw_key: str, run_time: datetime | None = None) -> dict:
    """Summarise a validation run as a JSON-friendly dictionary."""
    run_time = run_time or datetime.now(timezone.utc)
    parts = parse_raw_key(raw_key)
    rule_info = {r["id"]: r for r in rules["row_rules"]}

    return {
        "dataset": rules["dataset"],
        "source_file": raw_key,
        "partition": parts["partition"],
        "contract_version": rules["version"],
        "run_timestamp_utc": run_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "PASSED_WITH_WARNINGS" if result.warnings else "PASSED",
        "total_rows": result.total_rows,
        "valid_rows": len(result.valid),
        "rejected_rows": len(result.rejected),
        "flagged_rows": result.flagged_rows,
        "reject_rate": round(result.reject_rate, 4),
        "rule_failures": [
            {
                "rule_id": rule_id,
                "rule_name": rule_info[rule_id]["name"],
                "severity": rule_info[rule_id]["severity"],
                "failed_rows": count,
            }
            for rule_id, count in result.rule_failures.items()
        ],
        "warnings": result.warnings,
    }