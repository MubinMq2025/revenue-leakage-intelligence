"""
Tests for the checkout risk model (src/ml/order_risk.py).
"""

import pandas as pd
import pytest

from src.ml.order_risk import OUTCOMES, add_seller_history, capture

HISTORY = {"settle_days": 30, "k": 20, "prior": 0.01}


def orders_for(times, cancels, seller="S1"):
    return pd.DataFrame({"order_id": [f"o{i}" for i in range(len(times))], "main_seller_id": seller,
                         "purchased_at": pd.to_datetime(times), "canceled_after_payment": cancels})


def test_seller_history_only_counts_earlier_orders():
    df = add_seller_history(orders_for(["2017-01-01", "2017-01-05", "2017-03-01"], [1, 0, 0]), **HISTORY)
    assert df["seller_prior_orders"].tolist() == [0, 1, 2]
    assert df["is_new_seller"].tolist() == [1, 0, 0]


def test_recent_cancellations_are_not_known_yet():
    df = add_seller_history(orders_for(["2017-01-01", "2017-01-05", "2017-03-01"], [1, 0, 0]), **HISTORY)
    prior = 0.01
    # 5 Jan: the 1 Jan order is only 4 days old, so its cancellation is not counted yet
    assert df.loc[1, "seller_prior_cancel_rate"] == pytest.approx(prior)
    # 1 Mar: both January orders are settled: 1 cancel out of 2
    assert df.loc[2, "seller_prior_cancel_rate"] == pytest.approx((1 + prior * 20) / (2 + 20))


def test_an_order_does_not_see_its_own_outcome():
    a = add_seller_history(orders_for(["2017-01-01", "2017-03-01"], [0, 0]), **HISTORY)
    b = add_seller_history(orders_for(["2017-01-01", "2017-03-01"], [0, 1]), **HISTORY)
    pd.testing.assert_frame_equal(a.drop(columns="canceled_after_payment"), b.drop(columns="canceled_after_payment"))


def test_outcome_columns_are_never_listed_as_features():
    import yaml

    cfg = yaml.safe_load(open("config/ml.yaml", encoding="utf-8"))["order_risk"]
    assert not set(OUTCOMES) & set(cfg["numeric_features"] + cfg["categorical_features"])


def test_capture_counts_money_in_the_top_share():
    df = pd.DataFrame({"at_risk_rs": [100.0, 0, 0, 0, 300.0, 0, 0, 0, 0, 0],
                       "canceled_after_payment": [1, 0, 0, 0, 1, 0, 0, 0, 0, 0]})
    out = capture(df, [9, 1, 1, 1, 2, 1, 1, 1, 1, 1], share=0.1)      # reviews 1 order: the R$100 one
    assert out["money_caught"] == pytest.approx(0.25) and out["cancels_caught"] == pytest.approx(0.5)