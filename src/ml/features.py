"""
Point-in-time seller features for the Phase 4 models.

For every snapshot month T we pretend it is the 1st of that month and describe each seller
using only what was known at that moment:

    feature window = orders purchased in [T - lag - window, T - lag)
    label window   = orders purchased in [T, T + horizon)   (the future the model tries to predict)

The lag month (just before T) is skipped: its deliveries, reviews and cancellations are not settled yet.
Orders in the feature window that were delivered on or after T are treated as "not delivered yet"
(no late flag, no review), because at T nobody knew how they turned out.
"""

from __future__ import annotations

import pandas as pd

FEATURE_COLUMNS = [
    "orders", "revenue_rs", "at_risk_rate", "cancel_rate", "late_rate", "bad_review_rate",
    "avg_review", "freight_ratio", "avg_item_price", "orders_growth", "tenure_months",
]
LABEL_COLUMNS = ["future_orders", "future_revenue_rs", "future_at_risk_rs"]


def smooth_rate(numerator, denominator, prior, strength):
    """Blend a seller's own rate with the overall rate: (num + prior * k) / (den + k).

    Few orders -> close to the overall rate. Many orders -> close to the seller's own rate.
    """
    return (numerator + prior * strength) / (denominator + strength)


def windows(snapshot, cfg: dict) -> dict:
    """The date windows for one snapshot (start inclusive, end exclusive)."""
    t = pd.Timestamp(snapshot)
    feature_end = t - pd.DateOffset(months=cfg["lag_months"])
    return {
        "snapshot": t,
        "feature_start": feature_end - pd.DateOffset(months=cfg["window_months"]),
        "feature_end": feature_end,
        "label_end": t + pd.DateOffset(months=cfg["horizon_months"]),
    }


def months_between(start: pd.Series, end: pd.Timestamp) -> pd.Series:
    return (end.year - start.dt.year) * 12 + (end.month - start.dt.month)


def as_known_at(rows: pd.DataFrame, snapshot: pd.Timestamp) -> pd.DataFrame:
    """Hide delivery outcomes that happened on or after the snapshot date."""
    rows = rows.copy()
    not_yet = rows["delivered_date"].notna() & (rows["delivered_date"] >= snapshot)
    rows.loc[not_yet, ["is_delivered", "is_late"]] = 0
    rows.loc[not_yet, "review_score"] = float("nan")
    return rows


def build_snapshot(orders: pd.DataFrame, snapshot, cfg: dict) -> pd.DataFrame:
    """One row per seller with orders in the feature window: features as known at T, plus labels."""
    w = windows(snapshot, cfg)
    month = orders["purchase_month"]
    past = orders[(month >= w["feature_start"]) & (month < w["feature_end"])]
    future = orders[(month >= w["snapshot"]) & (month < w["label_end"])]
    if past.empty:
        return pd.DataFrame()

    past = as_known_at(past, w["snapshot"])
    recent_start = w["feature_end"] - pd.DateOffset(months=3)
    past = past.assign(
        has_review=past["review_score"].notna().astype(int),
        is_bad_review=(past["review_score"] <= 2).astype(int),
        is_recent=(past["purchase_month"] >= recent_start).astype(int),
    )

    f = past.groupby("seller_id").agg(
        orders=("order_id", "size"),
        recent_orders=("is_recent", "sum"),
        items=("items", "sum"),
        revenue_rs=("paid_rs", "sum"),
        at_risk_rs=("at_risk_rs", "sum"),
        price_rs=("price_rs", "sum"),
        freight_rs=("freight_rs", "sum"),
        canceled=("is_canceled", "sum"),
        delivered=("is_delivered", "sum"),
        late=("is_late", "sum"),
        reviews=("has_review", "sum"),
        bad_reviews=("is_bad_review", "sum"),
        review_points=("review_score", "sum"),
    )

    # Overall rates in this window (the "average seller"), used as priors for smoothing
    k = cfg["smoothing_strength"]
    avg_order_value = f["revenue_rs"].sum() / f["orders"].sum()
    f["at_risk_rate"] = smooth_rate(f["at_risk_rs"], f["revenue_rs"],
                                    f["at_risk_rs"].sum() / f["revenue_rs"].sum(), k * avg_order_value)
    f["cancel_rate"] = smooth_rate(f["canceled"], f["orders"], f["canceled"].sum() / f["orders"].sum(), k)
    f["late_rate"] = smooth_rate(f["late"], f["delivered"], f["late"].sum() / f["delivered"].sum(), k)
    f["bad_review_rate"] = smooth_rate(f["bad_reviews"], f["reviews"], f["bad_reviews"].sum() / f["reviews"].sum(), k)
    f["avg_review"] = smooth_rate(f["review_points"], f["reviews"], f["review_points"].sum() / f["reviews"].sum(), k)
    f["freight_ratio"] = f["freight_rs"] / f["price_rs"]
    f["avg_item_price"] = f["price_rs"] / f["items"]
    f["orders_growth"] = (f["recent_orders"] + 1) / (f["orders"] - f["recent_orders"] + 1)  # last 3 months vs 3 before

    first_seen = orders[month < w["feature_end"]].groupby("seller_id")["purchase_month"].min()
    f["tenure_months"] = months_between(first_seen.reindex(f.index), w["snapshot"])

    labels = future.groupby("seller_id").agg(
        future_orders=("order_id", "size"),
        future_revenue_rs=("paid_rs", "sum"),
        future_at_risk_rs=("at_risk_rs", "sum"),
    )
    f = f.join(labels).fillna({c: 0 for c in LABEL_COLUMNS})

    f.insert(0, "snapshot", w["snapshot"])
    return f.reset_index()[["snapshot", "seller_id", *FEATURE_COLUMNS, *LABEL_COLUMNS]]


def build_features(orders: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Every snapshot from first_snapshot to last_snapshot, stacked into one table."""
    snapshots = pd.date_range(cfg["first_snapshot"], cfg["last_snapshot"], freq="MS")
    return pd.concat([build_snapshot(orders, t, cfg) for t in snapshots], ignore_index=True)


def hidden_delivery_share(orders: pd.DataFrame, cfg: dict) -> float:
    """Share of delivered orders in the feature windows whose delivery happened after the snapshot.

    These are the outcomes as_known_at() hides. A big number means the lag is too short.
    """
    hidden = total = 0
    for t in pd.date_range(cfg["first_snapshot"], cfg["last_snapshot"], freq="MS"):
        w = windows(t, cfg)
        past = orders[(orders["purchase_month"] >= w["feature_start"]) & (orders["purchase_month"] < w["feature_end"])]
        delivered = past["delivered_date"].notna()
        hidden += int((delivered & (past["delivered_date"] >= t)).sum())
        total += int(delivered.sum())
    return hidden / total if total else 0.0