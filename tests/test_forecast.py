"""
Tests for the weekly revenue forecast (src/ml/forecast.py), using made-up weekly revenue.

As with the seller model, the key test is that nothing after the origin week can change a forecast.
"""

import numpy as np
import pandas as pd
import pytest

from src.ml.forecast import add_intervals, backtest, wape, weekly_revenue

CFG = {
    "horizons": [1, 2], "first_origin": "2017-03-06", "black_friday_weeks": ["2017-11-20"],
    "random_state": 42,
    "lightgbm": {"params": {"objective": "regression_l1", "n_estimators": 20, "num_leaves": 3,
                            "min_child_samples": 2, "verbose": -1}},
}


@pytest.fixture
def series():
    weeks = pd.date_range("2017-01-02", periods=20, freq="W-MON")
    rng = np.random.default_rng(0)
    return pd.Series(1000 + 50 * np.arange(20) + rng.normal(0, 30, 20), index=weeks)


def test_weekly_revenue_starts_weeks_on_monday_and_fills_gaps():
    orders = pd.DataFrame({"purchase_date_key": pd.to_datetime(["2017-01-04", "2017-01-08", "2017-01-18"]),
                           "paid_amount": [10.0, 5.0, 7.0]})
    s = weekly_revenue(orders, "2017-01-02", "2017-01-16")
    assert s.tolist() == [15.0, 0.0, 7.0]           # Wed + Sun of week 1, empty week 2, week 3


def test_changing_the_future_does_not_change_forecasts(series):
    origin = pd.Timestamp("2017-03-06")
    changed = series.copy()
    changed[changed.index > origin] *= 10          # rewrite everything after the origin
    a = backtest(series, CFG)
    b = backtest(changed, CFG)
    pick = lambda r: r[r["origin"] == origin].set_index(["horizon", "method"])["forecast"]
    pd.testing.assert_series_equal(pick(a), pick(b))


def test_ranges_only_use_errors_known_at_the_origin():
    results = pd.DataFrame({
        "origin": pd.to_datetime(["2017-01-02", "2017-01-09", "2017-01-16"]),
        "target_week": pd.to_datetime(["2017-01-09", "2017-01-16", "2017-01-23"]),
        "horizon": 1, "method": "naive", "forecast": [100.0, 100.0, 100.0], "actual": [110.0, 90.0, 500.0],
    })
    out = add_intervals(results, coverage=0.8, min_past_errors=2).set_index("origin")
    assert np.isnan(out.loc["2017-01-09", "low"])          # only 1 known error so far: no range yet
    assert out.loc["2017-01-16", "high"] < 120             # the 500 surprise is not known yet


def test_wape_is_total_error_over_total_actual():
    assert wape([200, 100], [180, 110]) == pytest.approx(30 / 300)