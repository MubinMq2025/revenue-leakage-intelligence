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



def test_a_tie_on_the_tuning_months_goes_to_the_first_method_in_the_tie_break_list():
    from src.ml.order_risk import select_winner

    tuning = pd.Series({"biggest_order": 0.093, "lightgbm": 0.132, "expected_loss": 0.132})
    assert select_winner(tuning, ["expected_loss", "biggest_order", "lightgbm"]) == ("expected_loss", ["lightgbm", "expected_loss"])
    assert select_winner(pd.Series({"a": 0.2, "b": 0.1}), ["b", "a"]) == ("a", ["a"])   # no tie: best wins


def test_bootstrap_ranges_are_wide_when_one_big_order_holds_the_money():
    import numpy as np

    from src.ml.order_risk import bootstrap_capture

    money = np.zeros(1000)
    money[0] = 10_000.0                      # one huge cancelled order holds almost all the money
    money[500:510] = 100.0                   # small cancelled orders the size ranking puts far down
    df = pd.DataFrame({"at_risk_rs": money})
    sizes = np.arange(1000, 0, -1)           # "biggest order first": order 0 is ranked first
    samples = bootstrap_capture(df, {"biggest_order": sizes}, share=0.01, samples=300, seed=1)
    low, high = samples["biggest_order"].quantile([0.05, 0.95])
    assert low < 0.1 and high > 0.8          # sometimes the huge order is drawn, sometimes nots