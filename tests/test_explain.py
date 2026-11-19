"""
Tests for the plain-English model explanations (src/ml/explain.py).
"""

import numpy as np
import pandas as pd
import pytest

from src.ml.explain import contributions, importance, reason_text, top_reasons


@pytest.fixture(scope="module")
def model_and_data():
    import lightgbm as lgb

    rng = np.random.default_rng(0)
    x = pd.DataFrame({"order_value_rs": rng.lognormal(4.5, 1, 3000), "promised_days": rng.integers(5, 60, 3000),
                      "purchase_hour": rng.integers(0, 24, 3000)}).astype(float)
    y = (rng.random(3000) < 0.02 + 0.10 * (x["promised_days"] > 40)).astype(int)   # long promises are risky
    model = lgb.LGBMClassifier(n_estimators=50, num_leaves=7, verbose=-1, random_state=0).fit(x, y)
    return model.booster_, x


def test_contributions_add_up_exactly_to_the_model_score(model_and_data):
    booster, x = model_and_data
    contrib = contributions(booster, x)
    np.testing.assert_allclose(contrib.sum(axis=1), booster.predict(x, raw_score=True), rtol=1e-6)


def test_the_input_that_drives_risk_is_the_most_important(model_and_data):
    booster, x = model_and_data
    assert importance(contributions(booster, x)).index[0] == "promised_days"


def test_reasons_are_in_words_and_only_list_inputs_that_push_risk_up():
    contrib = pd.Series({"order_value_rs": 0.9, "promised_days": 0.4, "purchase_hour": -0.3, "baseline": -5.0})
    values = pd.Series({"order_value_rs": 1850.0, "promised_days": 45.0, "purchase_hour": 14.0})
    assert top_reasons(contrib, values) == ["order worth R$1,850 (+0.90)", "delivery promised in 45 days (+0.40)"]


def test_reason_text_handles_categories_flags_and_unknown_inputs():
    assert reason_text("payment_types", "boleto") == "paid by boleto"
    assert reason_text("is_new_seller", 1) == "seller's first order"
    assert reason_text("something_new", 3) == "something_new = 3"