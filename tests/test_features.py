"""
Tests for the point-in-time seller features (src/ml/features.py), using small made-up data.

The most important test: anything that happens after the snapshot date must not change
the features. If it did, the model would be learning from the future (data leakage).
"""

import pandas as pd
import pytest

from src.ml.features import FEATURE_COLUMNS, build_snapshot, smooth_rate, windows

CFG = {"window_months": 6, "lag_months": 1, "horizon_months": 3, "smoothing_strength": 20}
SNAPSHOT = "2018-01-01"   # feature window Jun to Nov 2017, Dec 2017 skipped, label window Jan to Mar 2018


def order(seller, month, n=1, delivered=None, canceled=0, late=0, review=5.0, at_risk=0.0):
    return {
        "order_id": f"{seller}-{month}-{n}", "seller_id": seller,
        "purchase_month": pd.Timestamp(month), "items": 1, "price_rs": 100.0, "freight_rs": 20.0,
        "paid_rs": 120.0, "at_risk_rs": at_risk, "is_canceled": canceled,
        "is_delivered": int(delivered is not None), "is_late": late, "review_score": review,
        "delivered_date": pd.Timestamp(delivered) if delivered else pd.NaT,
    }


@pytest.fixture
def orders():
    return pd.DataFrame([
        order("A", "2017-07-01", 1, delivered="2017-07-10"),
        order("A", "2017-10-01", 2, delivered="2017-10-12", late=1, review=1.0),
        order("A", "2017-11-01", 3, delivered="2018-01-05", review=2.0),      # delivered AFTER the snapshot
        order("B", "2017-08-01", 1, canceled=1, at_risk=120.0, review=1.0),
        order("A", "2017-12-01", 4, canceled=1, at_risk=120.0),               # lag month: ignored
        order("A", "2018-02-01", 5, canceled=1, at_risk=120.0),               # label window
        order("B", "2018-05-01", 2, canceled=1, at_risk=120.0),               # after the label window
    ])


def features_of(df):
    return build_snapshot(df, SNAPSHOT, CFG).set_index("seller_id")[FEATURE_COLUMNS]


def test_smoothing_pulls_small_sellers_towards_the_average():
    assert smooth_rate(1, 1, 0.01, 20) == pytest.approx(0.0571, abs=1e-4)    # 1 of 1 cancelled: not 100%
    assert smooth_rate(50, 100, 0.01, 20) == pytest.approx(0.4183, abs=1e-4)  # 50 of 100: still clearly bad


def test_windows_skip_the_lag_month():
    w = windows(SNAPSHOT, CFG)
    assert w["feature_start"] == pd.Timestamp("2017-06-01")
    assert w["feature_end"] == pd.Timestamp("2017-12-01")
    assert w["label_end"] == pd.Timestamp("2018-04-01")


def test_deleting_the_future_does_not_change_features(orders):
    known = orders[orders["purchase_month"] < pd.Timestamp("2017-12-01")]
    pd.testing.assert_frame_equal(features_of(orders), features_of(known))


def test_outcomes_after_the_snapshot_are_hidden(orders):
    changed = orders.copy()
    late_delivery = changed["order_id"] == "A-2017-11-01-3"
    changed.loc[late_delivery, ["is_late", "review_score"]] = [1, 1.0]   # change what happened in January
    pd.testing.assert_frame_equal(features_of(orders), features_of(changed))


def test_labels_only_count_the_label_window(orders):
    snap = build_snapshot(orders, SNAPSHOT, CFG).set_index("seller_id")
    assert snap.loc["A", "future_orders"] == 1 and snap.loc["A", "future_at_risk_rs"] == 120.0
    assert snap.loc["B", "future_orders"] == 0     # B's May order is outside Jan to Mar


def test_one_row_per_active_seller(orders):
    snap = build_snapshot(orders, SNAPSHOT, CFG)
    assert sorted(snap["seller_id"]) == ["A", "B"]
    assert snap.loc[snap["seller_id"] == "A", "orders"].item() == 3   # the lag-month order is not counted