"""
Data quality validation engine.

Takes a DataFrame of raw rows plus one table's contract and returns:
  - valid rows (rows that broke a "warn" rule are kept, with their rule IDs in dq_flags)
  - rejected rows, each with the IDs of the "reject" rules it failed (rejection_reasons)
  - failure counts per rule and file-level warnings for the data quality report

The engine does no file or S3 I/O. That keeps it easy to test and lets the same
code run on a laptop, in AWS Lambda, or anywhere else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class ValidationResult:
    valid: pd.DataFrame
    rejected: pd.DataFrame
    rule_failures: dict[str, int]
    warnings: list[dict] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.valid) + len(self.rejected)

    @property
    def reject_rate(self) -> float:
        return len(self.rejected) / self.total_rows if self.total_rows else 0.0

    @property
    def flagged_rows(self) -> int:
        """Valid rows that broke at least one warn rule."""
        if "dq_flags" not in self.valid.columns:
            return 0
        return int((self.valid["dq_flags"] != "").sum())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cols(rule: dict) -> list[str]:
    """Rules can name one column ('column') or several ('columns')."""
    return rule["columns"] if "columns" in rule else [rule["column"]]


def _is_blank(series: pd.Series) -> pd.Series:
    return series.isna() | (series.astype(str).str.strip() == "")


def _any_blank(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    blank = pd.Series(False, index=df.index)
    for col in cols:
        blank |= _is_blank(df[col])
    return blank


def _parse(series: pd.Series, fmt: str) -> pd.Series:
    return pd.to_datetime(series, format=fmt, errors="coerce", utc=True)


# ---------------------------------------------------------------------------
# Row checks. Each returns a boolean Series: True = row FAILS the rule.
# All raw values are strings, so type problems can be detected, not crashed on.
# Blank values only fail not_null and required_if; other checks skip them.
# ---------------------------------------------------------------------------

def check_not_null(df, rule, **_):
    return _any_blank(df, _cols(rule))


def check_unique(df, rule, **_):
    cols = _cols(rule)
    # Keep the first occurrence; later repeats fail. Blank keys are handled by not_null.
    return df.duplicated(subset=cols, keep="first") & ~_any_blank(df, cols)


def check_numeric(df, rule, **_):
    failed = pd.Series(False, index=df.index)
    for col in _cols(rule):
        failed |= pd.to_numeric(df[col], errors="coerce").isna() & ~_is_blank(df[col])
    return failed


def check_range(df, rule, **_):
    failed = pd.Series(False, index=df.index)
    for col in _cols(rule):
        values = pd.to_numeric(df[col], errors="coerce")
        out = pd.Series(False, index=df.index)
        if "min_inclusive" in rule:
            out |= values < rule["min_inclusive"]
        if "min_exclusive" in rule:
            out |= values <= rule["min_exclusive"]
        if "max_inclusive" in rule:
            out |= values > rule["max_inclusive"]
        if "max_exclusive" in rule:
            out |= values >= rule["max_exclusive"]
        failed |= out & values.notna()  # non-numeric values are handled by check_numeric
    return failed


def check_timestamp_format(df, rule, ts_format, **_):
    fmt = rule.get("format", ts_format)
    failed = pd.Series(False, index=df.index)
    for col in _cols(rule):
        failed |= _parse(df[col], fmt).isna() & ~_is_blank(df[col])
    return failed


def check_not_future(df, rule, now, ts_format, **_):
    limit = pd.Timestamp(now + timedelta(minutes=rule.get("tolerance_minutes", 0)))
    failed = pd.Series(False, index=df.index)
    for col in _cols(rule):
        failed |= (_parse(df[col], rule.get("format", ts_format)) > limit).fillna(False)
    return failed


def check_allowed_values(df, rule, **_):
    allowed = [str(v) for v in rule["values"]]
    failed = pd.Series(False, index=df.index)
    for col in _cols(rule):
        failed |= ~df[col].isin(allowed) & ~_is_blank(df[col])
    return failed


def check_date_between(df, rule, ts_format, **_):
    """Dates must fall inside [min, max] (whole days, max day included)."""
    start = pd.Timestamp(rule["min"], tz="UTC")
    # Day after max, worked out in plain Python (avoids a NumPy deprecation warning)
    next_day = datetime.fromisoformat(str(rule["max"])) + timedelta(days=1)
    end_exclusive = pd.Timestamp(next_day, tz="UTC")
    failed = pd.Series(False, index=df.index)
    for col in _cols(rule):
        parsed = _parse(df[col], rule.get("format", ts_format))
        failed |= ((parsed < start) | (parsed >= end_exclusive)).fillna(False)
    return failed


def check_required_if(df, rule, **_):
    """Column must be filled when when_column has one of when_values."""
    condition = df[rule["when_column"]].isin([str(v) for v in rule["when_values"]])
    return condition & _any_blank(df, _cols(rule))


ROW_CHECKS = {
    "not_null": check_not_null,
    "unique": check_unique,
    "numeric": check_numeric,
    "range": check_range,
    "timestamp_format": check_timestamp_format,
    "not_future": check_not_future,
    "allowed_values": check_allowed_values,
    "date_between": check_date_between,
    "required_if": check_required_if,
}


def _rule_ids_per_row(failures: pd.DataFrame, rows: pd.Series) -> pd.Series:
    """For the selected rows, join the IDs of the rules they failed: 'OR001;OR004'."""
    subset = failures[rows]
    if subset.empty:
        return pd.Series(dtype=object)
    return subset.apply(lambda r: ";".join(r.index[r]), axis=1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate(df: pd.DataFrame, rules: dict, now: datetime | None = None) -> ValidationResult:
    """Apply every row rule, split valid/rejected rows, flag warnings, then apply file rules."""
    now = now or datetime.now(timezone.utc)
    ts_format = rules.get("timestamp_format", DEFAULT_TS_FORMAT)

    missing = [c for c, spec in rules["columns"].items() if spec.get("required") and c not in df.columns]
    if missing:
        raise ValueError(f"{rules['dataset']}: input is missing required columns: {missing}")

    df = df.reset_index(drop=True)
    reject_fail = pd.DataFrame(index=df.index)
    warn_fail = pd.DataFrame(index=df.index)
    rule_failures: dict[str, int] = {}

    for rule in rules["row_rules"]:
        failed = ROW_CHECKS[rule["check"]](df, rule, now=now, ts_format=ts_format).astype(bool)
        rule_failures[rule["id"]] = int(failed.sum())
        target = reject_fail if rule["severity"] == "reject" else warn_fail
        target[rule["id"]] = failed
        logger.info("%s %-6s %-36s failed rows: %s", rule["id"], rule["severity"], rule["name"], rule_failures[rule["id"]])

    is_rejected = reject_fail.any(axis=1) if not reject_fail.empty else pd.Series(False, index=df.index)
    is_flagged = warn_fail.any(axis=1) if not warn_fail.empty else pd.Series(False, index=df.index)

    rejected = df[is_rejected].copy()
    rejected["rejection_reasons"] = _rule_ids_per_row(reject_fail, is_rejected)

    valid = df[~is_rejected].copy()
    valid["dq_flags"] = ""
    keep_flagged = is_flagged & ~is_rejected
    if keep_flagged.any():
        valid.loc[keep_flagged[keep_flagged].index, "dq_flags"] = _rule_ids_per_row(warn_fail, keep_flagged)

    result = ValidationResult(valid=valid, rejected=rejected, rule_failures=rule_failures)
    result.warnings = _row_warnings(rules, rule_failures) + _apply_file_rules(rules.get("file_rules", []), result)
    return result


def _row_warnings(rules: dict, rule_failures: dict[str, int]) -> list[dict]:
    """Every warn rule that caught at least one row becomes a report warning."""
    return [
        {"rule_id": r["id"], "message": f"{rule_failures[r['id']]} rows flagged by {r['name']}"}
        for r in rules["row_rules"]
        if r["severity"] == "warn" and rule_failures[r["id"]] > 0
    ]


def _apply_file_rules(file_rules: list[dict], result: ValidationResult) -> list[dict]:
    warnings = []
    for rule in file_rules:
        if rule["check"] == "row_count_between":
            n = result.total_rows
            if not rule["min"] <= n <= rule["max"]:
                warnings.append({"rule_id": rule["id"], "message": f"Row count {n} outside expected range {rule['min']}-{rule['max']}"})
        elif rule["check"] == "reject_rate_below":
            if result.reject_rate >= rule["max_rate"]:
                warnings.append({"rule_id": rule["id"], "message": f"Reject rate {result.reject_rate:.1%} at or above {rule['max_rate']:.0%}"})
    for w in warnings:
        logger.warning("%s: %s", w["rule_id"], w["message"])
    return warnings