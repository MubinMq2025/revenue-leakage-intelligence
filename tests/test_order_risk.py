"""
Tests for the checkout risk model (src/ml/order_risk.py).
"""

import numpy as np
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

def test_the_model_does_not_depend_on_row_order():
    """Athena rewrites the mart in no fixed order; the same orders must always give the same model."""
    import yaml
    from pathlib import Path

    from src.ml.order_risk import model_inputs, train_model

    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "ml.yaml").read_text())["order_risk"]
    cfg = {**cfg, "lightgbm": {"params": {**cfg["lightgbm"]["params"], "n_estimators": 50}}}
    rng = np.random.default_rng(0)
    n = 3000
    df = pd.DataFrame({c: rng.normal(size=n) for c in cfg["numeric_features"]})
    for c in cfg["categorical_features"]:
        df[c] = rng.choice(["a", "b", "c"], size=n)
    df["order_id"] = [f"o{i:05d}" for i in range(n)]
    df["purchased_at"] = pd.Timestamp("2017-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D")
    df["canceled_after_payment"] = (rng.random(n) < 0.05 + 0.1 * (df[cfg["numeric_features"][0]] > 1)).astype(int)

    m1, cats1 = train_model(df, cfg)
    m2, cats2 = train_model(df.sample(frac=1, random_state=7), cfg)   # same orders, shuffled
    p1 = m1.predict_proba(model_inputs(df, cfg, cats1))[:, 1]
    p2 = m2.predict_proba(model_inputs(df, cfg, cats2))[:, 1]
    assert np.abs(p1 - p2).max() < 1e-12


def test_walk_forward_never_trains_on_the_month_it_scores():
    """Each month is scored by a model that only saw orders settled before that month."""
    import yaml
    from pathlib import Path

    from src.ml import order_risk

    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "ml.yaml").read_text())["order_risk"]
    cfg = {**cfg, "selection_start": "2017-10-01", "tuning_end": "2018-01-01",
           "lightgbm": {"params": {**cfg["lightgbm"]["params"], "n_estimators": 20}}}
    rng = np.random.default_rng(1)
    n = 6000
    df = pd.DataFrame({c: rng.normal(size=n) for c in cfg["numeric_features"]})
    for c in cfg["categorical_features"]:
        df[c] = rng.choice(["a", "b"], size=n)
    df["order_id"] = [f"o{i:05d}" for i in range(n)]
    df["purchased_at"] = pd.Timestamp("2017-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D")
    df["canceled_after_payment"] = (rng.random(n) < 0.05).astype(int)
    df["paid_rs"] = df["order_value_rs"] = rng.gamma(2, 80, n)
    df["at_risk_rs"] = df["paid_rs"] * df["canceled_after_payment"]

    latest_seen = []
    real_train = order_risk.train_model
    def spy(train, cfg, seed=None):
        latest_seen.append(train["purchased_at"].max())
        return real_train(train, cfg, seed)
    order_risk.train_model = spy
    try:
        windows = order_risk.walk_forward_capture(df, cfg)
    finally:
        order_risk.train_model = real_train

    assert list(windows["window"].unique()) == ["2017-10", "2017-11", "2017-12"]
    for seen, month in zip(latest_seen, ["2017-10-01", "2017-11-01", "2017-12-01"]):
        assert seen < pd.Timestamp(month) - pd.Timedelta(days=cfg["settle_days"])


def test_the_simple_rule_stays_unless_a_model_clearly_wins():
    from src.ml.order_risk import choose_method

    def windows(model_scores, baseline_scores):
        rows = []
        for i, (m, b) in enumerate(zip(model_scores, baseline_scores)):
            rows += [{"window": f"w{i}", "method": "lightgbm", "money_caught": m},
                     {"window": f"w{i}", "method": "biggest_order", "money_caught": b}]
        return pd.DataFrame(rows)

    # wins 2 of 6 months, one by a mile: not clearly better, baseline stays
    lucky = windows([0.90, 0.30, 0.05, 0.05, 0.05, 0.05], [0.10] * 6)
    assert choose_method(lucky, "biggest_order", 0.67, 0.02)["winner"] == "biggest_order"
    # big median lead but wins only half the months: baseline stays
    half = windows([0.40, 0.40, 0.40, 0.09, 0.09, 0.09], [0.10] * 6)
    assert choose_method(half, "biggest_order", 0.67, 0.02)["winner"] == "biggest_order"
    # wins most months but by a hair: baseline stays
    hair = windows([0.105] * 6, [0.10] * 6)
    assert choose_method(hair, "biggest_order", 0.67, 0.02)["winner"] == "biggest_order"
    # wins 5 of 6 months by 5+ points: the model earns its place
    clear = windows([0.20, 0.18, 0.16, 0.20, 0.17, 0.05], [0.10] * 6)
    assert choose_method(clear, "biggest_order", 0.67, 0.02)["winner"] == "lightgbm"
