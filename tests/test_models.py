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


def test_dimensions_are_built_before_facts():
    layers = [f.parent.name for f in create_models.model_files()]
    assert layers == sorted(layers)          # "dims" sorts before "facts"
    assert layers.count("dims") == 4 and layers.count("facts") == 3


def test_every_model_file_creates_a_view():
    for f in create_models.model_files():
        assert "CREATE OR REPLACE VIEW" in f.read_text(encoding="utf-8")


def test_run_query_returns_id_on_success():
    assert run_query(FakeAthena(), "SELECT 1") == "q1"


def test_run_query_raises_with_reason_on_failure():
    with pytest.raises(RuntimeError, match="bad SQL"):
        run_query(FakeAthena(final_state="FAILED"), "SELECT nonsense")


def test_fetch_rows_uses_first_row_as_header():
    athena = FakeAthena(rows=[["check_name", "result"], ["orders", "99441"]])
    assert fetch_rows(athena, "q1") == [{"check_name": "orders", "result": "99441"}]
