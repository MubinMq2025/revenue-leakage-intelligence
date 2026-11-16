"""
Load and lightly validate the data contracts (config/contracts/<table>.yaml).

There is one contract per table. Keeping rule loading separate from rule
checking means the same engine can run locally, in AWS Lambda, or in tests.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "config" / "contracts"

SUPPORTED_ROW_CHECKS = {
    "not_null", "unique", "numeric", "range", "timestamp_format",
    "not_future", "allowed_values", "date_between", "required_if",
}
SUPPORTED_FILE_CHECKS = {"row_count_between", "reject_rate_below"}
SEVERITIES = {"reject", "warn"}


def load_rules(path: Path | str) -> dict:
    """Read one YAML contract and fail fast if it contains unknown checks."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Contract not found: {path}")

    with path.open(encoding="utf-8") as f:
        rules = yaml.safe_load(f)

    for rule in rules.get("row_rules", []):
        if rule["check"] not in SUPPORTED_ROW_CHECKS:
            raise ValueError(f"{path.name} {rule['id']}: unsupported row check '{rule['check']}'")
        rule.setdefault("severity", "reject")
        if rule["severity"] not in SEVERITIES:
            raise ValueError(f"{path.name} {rule['id']}: severity must be one of {sorted(SEVERITIES)}")
    for rule in rules.get("file_rules", []):
        if rule["check"] not in SUPPORTED_FILE_CHECKS:
            raise ValueError(f"{path.name} {rule['id']}: unsupported file check '{rule['check']}'")

    return rules


def load_contract(table: str, contracts_dir: Path | str = CONTRACTS_DIR) -> dict:
    """Load the contract for one table, e.g. load_contract('orders')."""
    return load_rules(Path(contracts_dir) / f"{table}.yaml")


def load_all_contracts(contracts_dir: Path | str = CONTRACTS_DIR) -> dict[str, dict]:
    """Load every contract in the folder, keyed by table name."""
    return {p.stem: load_rules(p) for p in sorted(Path(contracts_dir).glob("*.yaml"))}