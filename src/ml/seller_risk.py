"""
Seller risk ranking and its backtest (Phase 4.2).

Each month the finance team can review a fixed number of sellers (the review queue).
A ranking method is useful if the sellers it puts at the top go on to cause a large share
of the money at risk over the next 3 months. We compare these methods on the same months:

    random                what a queue picked by chance would catch (the floor)
    biggest_revenue       "just review the biggest sellers" (size alone)
    worst_past_rate       "review the sellers with the worst at-risk rate so far" (a simple rule)
    isolation_forest      unusual behaviour, learned without labels
    lightgbm              learns from past outcomes which sellers went on to cause losses
    expected_loss         size x risk: revenue x smoothed at-risk rate (exposure x rate, as insurers do)
    lightgbm_regularized  lightgbm with smaller, more cautious trees (less likely to learn noise)

lightgbm is only trained on snapshots whose 3-month outcome was fully known before the test
month, so it never sees the answer it is graded on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.ml.features import FEATURE_COLUMNS

METHODS = ["random", "biggest_revenue", "worst_past_rate", "isolation_forest", "lightgbm",
           "expected_loss", "lightgbm_regularized"]


def model_matrix(df: pd.DataFrame, columns: list[str], log_columns: list[str]) -> pd.DataFrame:
    """The model inputs, with long-tailed columns on a log scale."""
    x = df[columns].astype(float).copy()
    for col in set(columns) & set(log_columns):
        x[col] = np.log1p(x[col])
    return x


def training_snapshots(snapshots, test_snapshot, horizon_months: int) -> list[pd.Timestamp]:
    """Snapshots whose label window ended on or before the test snapshot (outcome already known)."""
    cutoff = pd.Timestamp(test_snapshot) - pd.DateOffset(months=horizon_months)
    return [s for s in snapshots if s <= cutoff]


def isolation_forest_scores(snap: pd.DataFrame, cfg: dict) -> np.ndarray:
    """Higher = more unusual. Fitted on this month's sellers only (uses no labels)."""
    from sklearn.ensemble import IsolationForest

    x = model_matrix(snap, cfg["isolation_forest"]["features"], cfg["log_columns"])
    forest = IsolationForest(n_estimators=cfg["isolation_forest"]["n_estimators"],
                             random_state=cfg["random_state"]).fit(x)
    return -forest.score_samples(x)


def lightgbm_scores(train: pd.DataFrame, snap: pd.DataFrame, cfg: dict, variant: str = "lightgbm") -> np.ndarray:
    """Predicted money at risk over the next 3 months, learned from past snapshots."""
    import lightgbm as lgb

    # Fixed row order: bagging picks rows by position (see order_risk.train_model)
    train = train.sort_values(["snapshot", "seller_id"], kind="mergesort").reset_index(drop=True)
    model = lgb.LGBMRegressor(**cfg[variant]["params"], random_state=cfg["random_state"], deterministic=True,
                              force_row_wise=True, n_jobs=1)
    model.fit(model_matrix(train, FEATURE_COLUMNS, cfg["log_columns"]), train["future_at_risk_rs"])
    return model.predict(model_matrix(snap, FEATURE_COLUMNS, cfg["log_columns"]))


def method_scores(train: pd.DataFrame, snap: pd.DataFrame, cfg: dict) -> dict:
    """Every method's score for each seller in one snapshot (higher = review first)."""
    return {
        "biggest_revenue": snap["revenue_rs"].to_numpy(),
        "worst_past_rate": snap["at_risk_rate"].to_numpy(),
        "isolation_forest": isolation_forest_scores(snap, cfg),
        "lightgbm": lightgbm_scores(train, snap, cfg),
        "expected_loss": (snap["revenue_rs"] * snap["at_risk_rate"]).to_numpy(),
        "lightgbm_regularized": lightgbm_scores(train, snap, cfg, variant="lightgbm_regularized"),
    }


def capture(snap: pd.DataFrame, scores, k: int, total_future_risk: float) -> float:
    """Share of all seller-attributable future money at risk caught by the top k sellers."""
    if total_future_risk <= 0:
        return float("nan")
    top = snap.assign(score=scores).nlargest(k, "score")
    return float(top["future_at_risk_rs"].sum() / total_future_risk)


def backtest(features: pd.DataFrame, total_future_risk: dict, cfg: dict, horizon_months: int,
             ks=(5, 10, 20, 50, 100, 200)) -> pd.DataFrame:
    """Score every method on every test month. One row per (snapshot, method, k)."""
    snapshots = sorted(features["snapshot"].unique())
    tests = [s for s in snapshots if s >= pd.Timestamp(cfg["first_test_snapshot"])]
    rows = []
    for t in tests:
        snap = features[features["snapshot"] == t].reset_index(drop=True)
        total = total_future_risk[pd.Timestamp(t)]
        train = features[features["snapshot"].isin(training_snapshots(snapshots, t, horizon_months))]
        scores = method_scores(train, snap, cfg)
        for k in ks:
            k_eff = min(k, len(snap))
            # Random queue: on average it catches k/N of the risk held by active sellers
            rows.append({"snapshot": t, "method": "random", "k": k,
                         "capture": k_eff / len(snap) * snap["future_at_risk_rs"].sum() / total})
            for method, s in scores.items():
                rows.append({"snapshot": t, "method": method, "k": k, "capture": capture(snap, s, k_eff, total)})
    return pd.DataFrame(rows)


def select_method(results: pd.DataFrame, tuning_end, k: int) -> tuple[str, pd.DataFrame]:
    """Pick the method with the best average top-k capture on the tuning months only.

    Returns the winner and a table of every method's average on tuning vs holdout months.
    The holdout months play no part in the choice, so their numbers are an honest test.
    """
    at_k = results[(results["k"] == k) & (results["method"] != "random")].copy()
    at_k["period"] = np.where(at_k["snapshot"] < pd.Timestamp(tuning_end), "tuning", "holdout")
    table = at_k.pivot_table(index="method", columns="period", values="capture", aggfunc="mean")
    winner = table["tuning"].idxmax()
    return winner, table[["tuning", "holdout"]].sort_values("tuning", ascending=False)