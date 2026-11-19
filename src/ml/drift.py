"""
Drift checks (Phase 4.5b): warn when the data or a model's results stop looking like before.

Three checks:

    size/price drift   the sellers changed shape. Measured with PSI (Population Stability Index): split
                       the early values into 10 equal groups, then see how the recent values spread
                       over those same groups. Same spread -> PSI near 0. Very different -> high PSI.
    behaviour drift    overall cancel, late, bad-review and at-risk rates, same months a year apart.
    performance decay  the results got worse. Compare the chosen method's recent score with its
                       earlier score.

Each check returns a status (OK, WATCH or ALERT) so Phase 5 can send an alert automatically.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def psi(reference, current, bins: int = 10) -> float:
    """Population Stability Index between two samples, using the reference sample's deciles."""
    reference = np.asarray(reference, float)
    current = np.asarray(current, float)
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    ref_share = np.histogram(reference, edges)[0] / len(reference)
    cur_share = np.histogram(current, edges)[0] / len(current)
    ref_share, cur_share = np.clip(ref_share, 1e-4, None), np.clip(cur_share, 1e-4, None)  # avoid log(0)
    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))


def psi_status(value: float, watch: float, alert: float) -> str:
    return "ALERT" if value > alert else "WATCH" if value > watch else "OK"


def feature_drift(features: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """PSI per seller feature (size and price), early period vs latest period."""
    snap = features["snapshot"]
    ref = features[snap.isin(pd.to_datetime(cfg["reference_snapshots"]))]
    cur = features[snap.isin(pd.to_datetime(cfg["current_snapshots"]))]
    rows = []
    for col in cfg["features"]:
        value = psi(ref[col], cur[col], cfg["psi_bins"])
        rows.append({"feature": col, "psi": value, "status": psi_status(value, cfg["psi_watch"], cfg["psi_alert"]),
                     "reference_median": float(ref[col].median()), "current_median": float(cur[col].median())})
    return pd.DataFrame(rows).sort_values("psi", ascending=False).reset_index(drop=True)


def overall_rates(orders: pd.DataFrame) -> dict:
    """Pooled rates over a set of order-seller rows (every order counts once, big sellers weigh more)."""
    reviewed = orders["review_score"].notna()
    return {
        "cancel_rate": orders["is_canceled"].sum() / len(orders),
        "late_rate": orders["is_late"].sum() / orders["is_delivered"].sum(),
        "bad_review_rate": (orders.loc[reviewed, "review_score"] <= 2).mean(),
        "at_risk_rate": orders["at_risk_rs"].sum() / orders["paid_rs"].sum(),
    }


def rate_drift(orders: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Each overall rate in the reference months vs the current months, as a relative change."""
    month = orders["purchase_month"]
    before = overall_rates(orders[month.isin(pd.to_datetime(cfg["reference_months"]))])
    after = overall_rates(orders[month.isin(pd.to_datetime(cfg["current_months"]))])
    rows = []
    for name in before:
        change = after[name] / before[name] - 1 if before[name] else float("nan")
        status = "ALERT" if abs(change) > cfg["rate_alert"] else "WATCH" if abs(change) > cfg["rate_watch"] else "OK"
        rows.append({"rate": name, "before": float(before[name]), "after": float(after[name]),
                     "change": float(change), "status": status})
    return pd.DataFrame(rows)


def decay_check(name: str, early: float, recent: float, higher_is_better: bool, alert_ratio: float) -> dict:
    """Compare a recent score with an earlier one. alert_ratio 0.5 = alert if half as good."""
    ratio = recent / early if early else float("nan")
    worse = ratio < alert_ratio if higher_is_better else ratio > alert_ratio
    status = "ALERT" if worse else "OK"
    return {"check": name, "early": float(early), "recent": float(recent), "ratio": float(ratio), "status": status}


def seller_queue_decay(results: pd.DataFrame, method: str, k: int, cfg: dict) -> dict:
    """The chosen queue's capture in the last N test months vs the first N."""
    at_k = results[(results["method"] == method) & (results["k"] == k)].sort_values("snapshot")["capture"]
    n = cfg["decay_months"]
    return decay_check(f"seller_queue_capture_top{k}.{method}", at_k.head(n).mean(), at_k.tail(n).mean(),
                       higher_is_better=True, alert_ratio=cfg["decay_alert_ratio"])


def forecast_decay(results: pd.DataFrame, method: str, cfg: dict, wape) -> dict:
    """The chosen forecast's 1-week-ahead WAPE over the last N weeks vs the whole backtest."""
    one = results[(results["method"] == method) & (results["horizon"] == 1)].sort_values("target_week")
    recent = one.tail(cfg["forecast_recent_weeks"])
    return decay_check(f"forecast_wape_1w.{method}", wape(one["actual"], one["forecast"]),
                       wape(recent["actual"], recent["forecast"]),
                       higher_is_better=False, alert_ratio=cfg["forecast_alert_ratio"])


def overall_status(statuses) -> str:
    statuses = list(statuses)
    return "ALERT" if "ALERT" in statuses else "WATCH" if "WATCH" in statuses else "OK"