"""
Tests for the drift checks (src/ml/drift.py).
"""

import numpy as np
import pytest

from src.ml.drift import decay_check, overall_status, psi, psi_status


def test_psi_is_near_zero_for_the_same_distribution_and_high_for_a_shifted_one():
    rng = np.random.default_rng(0)
    before = rng.normal(100, 10, 5000)
    assert psi(before, rng.normal(100, 10, 5000)) < 0.02          # same shape: stable
    assert psi(before, rng.normal(120, 10, 5000)) > 0.25          # moved by 2 standard deviations: drift


def test_psi_thresholds():
    assert [psi_status(v, 0.10, 0.25) for v in (0.05, 0.15, 0.40)] == ["OK", "WATCH", "ALERT"]


def test_decay_alerts_when_a_score_halves_or_an_error_grows():
    assert decay_check("queue", early=0.20, recent=0.08, higher_is_better=True, alert_ratio=0.5)["status"] == "ALERT"
    assert decay_check("queue", early=0.20, recent=0.15, higher_is_better=True, alert_ratio=0.5)["status"] == "OK"
    assert decay_check("wape", early=0.18, recent=0.30, higher_is_better=False, alert_ratio=1.5)["status"] == "ALERT"
    assert decay_check("wape", early=0.18, recent=0.20, higher_is_better=False, alert_ratio=1.5)["ratio"] == pytest.approx(1.111, abs=1e-3)


def test_overall_status_is_the_worst_one():
    assert overall_status(["OK", "WATCH", "OK"]) == "WATCH"
    assert overall_status(["OK", "ALERT", "WATCH"]) == "ALERT"
    assert overall_status(["OK"]) == "OK"


def test_rate_drift_flags_a_big_change_in_cancellations_only():
    import pandas as pd

    from src.ml.drift import rate_drift

    def month(when, n, cancels):
        return pd.DataFrame({"purchase_month": pd.Timestamp(when), "is_canceled": [1] * cancels + [0] * (n - cancels),
                             "is_delivered": [0] * cancels + [1] * (n - cancels), "is_late": 0,
                             "review_score": 5.0, "at_risk_rs": 0.0, "paid_rs": 100.0})

    orders = pd.concat([month("2017-04-01", 1000, 10), month("2018-04-01", 1000, 20)])   # 1% -> 2% cancelled
    cfg = {"reference_months": ["2017-04-01"], "current_months": ["2018-04-01"], "rate_watch": 0.25, "rate_alert": 0.50}
    result = rate_drift(orders, cfg).set_index("rate")
    assert result.loc["cancel_rate", "change"] == pytest.approx(1.0)                   # doubled = +100%
    assert result.loc["cancel_rate", "status"] == "ALERT"
    assert result.loc["late_rate", "status"] == "OK"