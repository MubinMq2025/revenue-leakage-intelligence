"""
Tests for the model build script and the Athena helpers, using a fake Athena client.
"""

import importlib.util
from pathlib import Path

import pytest

from src.athena_tools import fetch_rows, run_query

REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("create_models", REPO_ROOT / "scripts" / "create_models.py")
create_models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(create_models)


class FakeAthena:
    """Pretends to be Athena: every query ends in the state we choose."""

    def __init__(self, final_state="SUCCEEDED", rows=None):
        self.final_state = final_state
        self.rows = rows or []
        self.queries = []

    def start_query_execution(self, QueryString, **kwargs):
        self.queries.append(QueryString)
        return {"QueryExecutionId": f"q{len(self.queries)}"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": self.final_state, "StateChangeReason": "bad SQL"}}}

    def get_paginator(self, name):
        rows = self.rows

        class Paginator:
            def paginate(self, **kwargs):
                yield {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": v} for v in r]} for r in rows]}}

        return Paginator()


def test_layers_are_built_in_order():
    layers = [f.parent.name for f, _ in create_models.model_files()]
    positions = [create_models.LAYER_NAMES.index(layer) for layer in layers]
    assert positions == sorted(positions)    # dims, then facts, then recon, then marts
    assert layers.count("dims") == 4 and layers.count("facts") == 3


def test_view_files_create_views_and_mart_files_are_selects():
    for f, kind in create_models.model_files():
        sql = f.read_text(encoding="utf-8")
        if kind == "view":
            assert "CREATE OR REPLACE VIEW" in sql
        else:
            code = [line for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")]
            assert code[0].split()[0].upper() in ("SELECT", "WITH")   # the script adds CREATE TABLE AS


def test_marts_are_built_after_the_marts_they_read():
    marts = [f.stem for f, kind in create_models.model_files() if kind == "table"]
    assert marts.index("mart_order_reconciliation") < marts.index("mart_leakage_summary")


def test_dependency_order_and_cycle_detection(tmp_path):
    (tmp_path / "a_summary.sql").write_text("SELECT * FROM db.b_detail")
    (tmp_path / "b_detail.sql").write_text("SELECT 1")
    files = sorted(tmp_path.glob("*.sql"))
    assert [f.stem for f in create_models.dependency_order(files)] == ["b_detail", "a_summary"]

    (tmp_path / "b_detail.sql").write_text("SELECT * FROM db.a_summary")
    with pytest.raises(ValueError, match="Circular"):
        create_models.dependency_order(sorted(tmp_path.glob("*.sql")))


def test_run_query_returns_id_on_success():
    assert run_query(FakeAthena(), "SELECT 1") == "q1"


def test_run_query_raises_with_reason_on_failure():
    with pytest.raises(RuntimeError, match="bad SQL"):
        run_query(FakeAthena(final_state="FAILED"), "SELECT nonsense")


def test_fetch_rows_uses_first_row_as_header():
    athena = FakeAthena(rows=[["check_name", "result"], ["orders", "99441"]])
    assert fetch_rows(athena, "q1") == [{"check_name": "orders", "result": "99441"}]


# --- check_models.py -----------------------------------------------------------

spec_checks = importlib.util.spec_from_file_location("check_models", REPO_ROOT / "scripts" / "check_models.py")
check_models = importlib.util.module_from_spec(spec_checks)
spec_checks.loader.exec_module(check_models)


def test_every_check_is_well_formed():
    for check in check_models.load_checks():
        assert {"name", "severity", "sql"} <= set(check)
        assert check["severity"] in ("error", "warn")
        assert "failures" in check["sql"]


def test_error_check_passes_only_at_zero():
    check = {"severity": "error"}
    assert check_models.evaluate(check, 0) == "PASS"
    assert check_models.evaluate(check, 3) == "FAIL"


def test_warn_check_compares_with_expected_number():
    check = {"severity": "warn", "expect": 775}
    assert check_models.evaluate(check, 775) == "KNOWN"
    assert check_models.evaluate(check, 780) == "CHANGED"


def test_run_check_reads_failures_from_athena():
    athena = FakeAthena(rows=[["failures"], ["0"]])
    _, failures, result = check_models.run_check(athena, {"severity": "error", "sql": "SELECT 0 AS failures"})
    assert (failures, result) == (0, "PASS")