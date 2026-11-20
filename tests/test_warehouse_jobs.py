"""
Tests for the Phase 5 warehouse jobs: the leakage decision and the "models" Lambda.
No AWS needed: Athena is faked, and the build/check functions are swapped out.
"""

import importlib

import pytest

from src.warehouse import leakage

handler = importlib.import_module("lambda.models_handler")

MONTH = {"month": "2018-08-01", "orders": "6512", "paid_rs": "1000000.00", "at_risk_rs": "5000.00"}  # 0.5%


# --- leakage decision ---------------------------------------------------------

def test_no_alert_below_the_line():
    result = leakage.decide(MONTH, max_rate=0.02, drift_status="OK", alert_on_drift=False)
    assert result["at_risk_rate"] == pytest.approx(0.005)
    assert result["alert"] is False and result["reasons"] == []


def test_alert_above_the_line():
    result = leakage.decide(MONTH, max_rate=0.001, drift_status="OK", alert_on_drift=False)
    assert result["alert"] is True
    assert "0.50%" in result["reasons"][0]


def test_drift_alert_only_emails_when_switched_on():
    quiet = leakage.decide(MONTH, max_rate=0.02, drift_status="ALERT", alert_on_drift=False)
    loud = leakage.decide(MONTH, max_rate=0.02, drift_status="ALERT", alert_on_drift=True)
    assert quiet["alert"] is False and quiet["drift_status"] == "ALERT"   # still reported
    assert loud["alert"] is True


def test_zero_paid_does_not_divide_by_zero():
    result = leakage.decide({**MONTH, "paid_rs": "0", "at_risk_rs": "0"}, 0.02, "OK", False)
    assert result["at_risk_rate"] == 0.0


def test_config_file_is_well_formed():
    cfg = leakage.load_alert_config()
    assert 0 < cfg["leakage"]["max_at_risk_rate"] < 1
    assert cfg["leakage"]["min_orders"] > 0
    assert isinstance(cfg["drift"]["alert_on_drift"], bool)


class FakeAthena:
    """Answers the month query and then the drift query."""

    def __init__(self, answers):
        self.answers = answers   # list of row lists, one per query, in order
        self.queries = []

    def start_query_execution(self, QueryString, **kwargs):
        self.queries.append(QueryString)
        return {"QueryExecutionId": f"q{len(self.queries)}"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_paginator(self, name):
        answers, queries = self.answers, self.queries

        class Paginator:
            def paginate(self, QueryExecutionId):
                rows = answers[int(QueryExecutionId[1:]) - 1]
                yield {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": v} for v in r]} for r in rows]}}

        return Paginator()


def test_check_leakage_reads_month_and_drift():
    athena = FakeAthena([
        [["month", "orders", "paid_rs", "at_risk_rs"], ["2018-08-01", "6512", "1000000", "5000"]],
        [["overall_status", "checked_at"], ["ALERT", "2026-11-19 23:36:00"]],
    ])
    result = leakage.check_leakage(athena)
    assert "HAVING COUNT(*) >= 1000" in athena.queries[0]
    assert result["drift_status"] == "ALERT" and result["alert"] is False
    assert "All clear" in result["summary"]


def test_check_leakage_override_forces_an_alert():
    athena = FakeAthena([
        [["month", "orders", "paid_rs", "at_risk_rs"], ["2018-08-01", "6512", "1000000", "5000"]],
        [["overall_status", "checked_at"], ["OK", "2026-11-19 23:36:00"]],
    ])
    result = leakage.check_leakage(athena, max_rate=0.001)
    assert result["alert"] is True and result["summary"].startswith("ALERT")


def test_check_leakage_fails_when_no_month_is_big_enough():
    athena = FakeAthena([[["month", "orders", "paid_rs", "at_risk_rs"]], []])
    with pytest.raises(RuntimeError, match="No month"):
        leakage.check_leakage(athena)


# --- the Lambda handler ----------------------------------------------------------

@pytest.fixture
def no_aws(monkeypatch):
    monkeypatch.setattr(handler, "athena_client", lambda: object())


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError, match="Unknown action"):
        handler.lambda_handler({"action": "dance"}, None)


def test_build_raises_when_a_model_fails(no_aws, monkeypatch):
    monkeypatch.setattr(handler, "build_all", lambda *a: [
        {"model": "dims/dim_date", "kind": "view", "status": "OK"},
        {"model": "marts/mart_x", "kind": "table", "status": "FAILED", "error": "bad SQL"},
    ])
    with pytest.raises(handler.StepFailed, match="1 of 2 models failed: marts/mart_x"):
        handler.lambda_handler({"action": "build"}, None)


def test_build_returns_a_summary_when_all_ok(no_aws, monkeypatch):
    monkeypatch.setattr(handler, "build_all", lambda *a: [{"model": "m", "kind": "view", "status": "OK"}] * 14)
    result = handler.lambda_handler({"action": "build"}, None)
    assert result["models"] == 14 and result["failed"] == 0 and result["action"] == "build"


def test_check_raises_on_a_changed_known_gap(no_aws, monkeypatch):
    monkeypatch.setattr(handler, "run_all", lambda athena: [
        {"name": "no_dupes", "severity": "error", "failures": 0, "expect": None, "result": "PASS"},
        {"name": "orders_without_items", "severity": "warn", "failures": 780, "expect": 775, "result": "CHANGED"},
    ])
    with pytest.raises(handler.StepFailed, match="orders_without_items"):
        handler.lambda_handler({"action": "check"}, None)


def test_leakage_passes_the_test_line_through(no_aws, monkeypatch):
    seen = {}
    monkeypatch.setattr(handler, "check_leakage", lambda athena, max_rate: seen.setdefault("rate", max_rate) and {})
    handler.lambda_handler({"action": "leakage", "max_at_risk_rate": 0.001}, None)
    assert seen["rate"] == 0.001


def test_leakage_reads_the_test_line_from_the_step_functions_input(no_aws, monkeypatch):
    seen = []
    monkeypatch.setattr(handler, "check_leakage", lambda athena, max_rate: seen.append(max_rate) or {})
    handler.lambda_handler({"action": "leakage", "input": {"max_at_risk_rate": 0.001}}, None)
    handler.lambda_handler({"action": "leakage", "input": {}}, None)   # a normal daily run
    assert seen == [0.001, None]
