"""
Tests for the seller risk backtest (src/ml/seller_risk.py).
"""

import numpy as np
import pandas as pd
import pytest

from src.ml.seller_risk import capture, isolation_forest_scores, select_method, training_snapshots

CFG = {
    "random_state": 42, "log_columns": ["orders_growth"],
    "isolation_forest": {"n_estimators": 100, "features": ["cancel_rate", "orders_growth"]},
}


def test_supervised_model_only_trains_on_outcomes_known_before_the_test_month():
    snapshots = list(pd.date_range("2017-04-01", "2017-12-01", freq="MS"))
    train = training_snapshots(snapshots, "2017-10-01", horizon_months=3)
    # The 2017-07 snapshot's outcome covers Jul to Sep, known by 1 Oct: allowed. 2017-08 is not.
    assert max(train) == pd.Timestamp("2017-07-01")


def test_capture_is_share_of_total_future_risk_caught_by_the_top_k():
    snap = pd.DataFrame({"future_at_risk_rs": [100.0, 0.0, 50.0, 0.0]})
    assert capture(snap, [0.9, 0.8, 0.1, 0.0], k=2, total_future_risk=200.0) == pytest.approx(0.5)
    assert capture(snap, [0.9, 0.0, 0.8, 0.1], k=2, total_future_risk=200.0) == pytest.approx(0.75)


def test_isolation_forest_scores_the_odd_seller_highest():
    rng = np.random.default_rng(0)
    snap = pd.DataFrame({"cancel_rate": rng.normal(0.01, 0.002, 200), "orders_growth": rng.normal(1, 0.1, 200)})
    snap.loc[0, ["cancel_rate", "orders_growth"]] = [0.40, 6.0]   # one clearly unusual seller
    assert np.argmax(isolation_forest_scores(snap, CFG)) == 0


def test_winner_is_chosen_on_tuning_months_only():
    months = pd.to_datetime(["2017-10-01", "2017-11-01", "2018-03-01", "2018-04-01"])
    rows = []
    for m in months:
        holdout = m >= pd.Timestamp("2018-03-01")
        rows.append({"snapshot": m, "method": "steady", "k": 20, "capture": 0.10})
        rows.append({"snapshot": m, "method": "lucky_later", "k": 20, "capture": 0.90 if holdout else 0.01})
    winner, table = select_method(pd.DataFrame(rows), "2018-03-01", k=20)
    assert winner == "steady"                       # great holdout numbers must not influence the choice
    assert table.loc["lucky_later", "holdout"] == pytest.approx(0.90)