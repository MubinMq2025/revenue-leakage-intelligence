"""
Plain-English reasons for the checkout risk model (Phase 4.8c), using SHAP values.

SHAP splits one order's score into a contribution from each input: starting from the average
order, "delivery promised in 45 days" pushed the risk up this much, "paid by credit card" pulled
it down that much, and so on. The contributions add up exactly to the model's score.
LightGBM computes them itself (pred_contrib=True), so no extra package is needed.

Contributions are in log-odds, the model's internal scale: +0.7 roughly doubles the chance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def contributions(booster, x: pd.DataFrame) -> pd.DataFrame:
    """One column per input with its SHAP contribution, plus 'baseline' (the average order)."""
    values = booster.predict(x, pred_contrib=True)
    return pd.DataFrame(values, columns=[*x.columns, "baseline"], index=x.index)


def reason_text(feature: str, value) -> str:
    """Describe one input value in words a finance reader understands."""
    if isinstance(value, float) and np.isnan(value):
        return f"{feature} unknown"
    templates = {
        "order_value_rs": lambda v: f"order worth R${v:,.0f}",
        "freight_rs": lambda v: f"delivery charge R${v:,.0f}",
        "freight_ratio": lambda v: f"delivery is {v:.0%} of the price",
        "item_count": lambda v: f"{int(v)} item(s) in the order",
        "seller_count": lambda v: f"{int(v)} seller(s) in the order",
        "max_installments": lambda v: f"paid in {int(v)} instalment(s)",
        "uses_voucher": lambda v: "paid partly with a voucher" if v else "no voucher used",
        "promised_days": lambda v: f"delivery promised in {int(v)} days",
        "purchase_hour": lambda v: f"bought at {int(v)}:00",
        "purchase_weekday": lambda v: f"bought on weekday {int(v)} (1 = Monday)",
        "same_state": lambda v: "seller and customer in the same state" if v else "seller in a different state",
        "seller_prior_orders": lambda v: f"seller had {int(v)} earlier order(s)",
        "seller_prior_cancel_rate": lambda v: f"seller's past cancel rate {v:.1%}",
        "is_new_seller": lambda v: "seller's first order" if v else "seller has history",
        "payment_types": lambda v: f"paid by {v}",
        "customer_state": lambda v: f"customer in {v}",
        "seller_state": lambda v: f"seller in {v}",
        "main_category": lambda v: f"category {v}",
    }
    return templates[feature](value) if feature in templates else f"{feature} = {value}"


def top_reasons(contrib: pd.Series, values: pd.Series, n: int = 3) -> list[str]:
    """The n inputs that pushed this order's risk up the most, in words."""
    pushes_up = contrib.drop("baseline").sort_values(ascending=False)
    pushes_up = pushes_up[pushes_up > 0].head(n)
    return [f"{reason_text(f, values[f])} (+{c:.2f})" for f, c in pushes_up.items()]


def importance(contrib: pd.DataFrame) -> pd.Series:
    """Average size of each input's push, across all orders: which inputs matter most overall."""
    return contrib.drop(columns="baseline").abs().mean().sort_values(ascending=False)