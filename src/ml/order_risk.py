"""
Checkout risk model (Phase 4.8): score every paid order for the chance it is cancelled after payment.

Inputs are only facts known when the customer pays (order value, delivery charge, payment type,
promised delivery days, states, category) plus the main seller's history up to that moment.
The label comes from the reconciliation: reason code CANCELED_BUT_PAID.

Ranking methods compared on the same orders (finance reviews the top 1%):

    random            what a random 1% would catch (the floor)
    biggest_order     "check the biggest orders" (size alone)
    lightgbm          the model's chance of cancellation
    expected_loss     chance x amount paid: which orders put the most money at risk

Train on 2017 orders, pick the best method on Jan to Mar 2018, confirm on Apr to Jul 2018 (unseen).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

METHODS = ["random", "biggest_order", "lightgbm", "expected_loss"]
OUTCOMES = ["order_status", "reason_code", "canceled_after_payment", "at_risk_rs"]   # never model inputs


def add_seller_history(orders: pd.DataFrame, settle_days: int, k: float, prior: float) -> pd.DataFrame:
    """For each order: how many orders its main seller had before, and their settled cancel rate.

    Only orders bought strictly before this one count. Cancellations only count once they are
    settle_days old, because at checkout we cannot know how a 3-day-old order will end.
    Rates are smoothed toward `prior`, the cancel rate of the training period (not of all data,
    which would leak later outcomes).
    """
    orders = orders.sort_values(["main_seller_id", "purchased_at"]).copy()
    prior_orders = np.zeros(len(orders))
    settled_orders = np.zeros(len(orders))
    settled_cancels = np.zeros(len(orders))
    settle = np.timedelta64(timedelta(days=settle_days))

    start = 0
    for _, group in orders.groupby("main_seller_id", sort=False):
        times = group["purchased_at"].to_numpy()
        cancels = np.concatenate([[0], np.cumsum(group["canceled_after_payment"].to_numpy())])
        end = start + len(group)
        prior_orders[start:end] = np.searchsorted(times, times, side="left")          # strictly earlier
        idx = np.searchsorted(times, times - settle, side="left")                     # old enough to know
        settled_orders[start:end] = idx
        settled_cancels[start:end] = cancels[idx]
        start = end

    orders["seller_prior_orders"] = prior_orders
    orders["seller_prior_cancel_rate"] = (settled_cancels + prior * k) / (settled_orders + k)
    orders["is_new_seller"] = (prior_orders == 0).astype(int)
    return orders.sort_index()


def model_inputs(df: pd.DataFrame, cfg: dict, categories: dict | None = None) -> pd.DataFrame:
    """Numeric features as numbers, text features as categories (with the training set's categories)."""
    x = df[cfg["numeric_features"]].astype(float).copy()
    for col in cfg["categorical_features"]:
        cats = categories[col] if categories else sorted(df[col].dropna().unique())
        x[col] = pd.Categorical(df[col], categories=cats)
    return x


def split(orders: pd.DataFrame, cfg: dict) -> dict:
    when = orders["purchased_at"]
    edges = [pd.Timestamp(cfg[k]) for k in ("train_start", "train_end", "tuning_end", "test_end")]
    return {
        "train": orders[(when >= edges[0]) & (when < edges[1])],
        "tuning": orders[(when >= edges[1]) & (when < edges[2])],
        "holdout": orders[(when >= edges[2]) & (when < edges[3])],
    }


def train_model(train: pd.DataFrame, cfg: dict, seed: int | None = None):
    import lightgbm as lgb

    # Fix the row order first. LightGBM's bagging (subsample) picks rows by position, so the same
    # orders in a different order give a different model. Athena rewrites the mart files on every
    # rebuild, in no fixed order, so without this the daily pipeline trained a new model each day.
    train = train.sort_values(["purchased_at", "order_id"], kind="mergesort").reset_index(drop=True)
    categories = {c: sorted(train[c].dropna().unique()) for c in cfg["categorical_features"]}
    seed = cfg["random_state"] if seed is None else seed
    model = lgb.LGBMClassifier(**cfg["lightgbm"]["params"], random_state=seed, deterministic=True,
                               force_row_wise=True, n_jobs=1)
    model.fit(model_inputs(train, cfg, categories), train["canceled_after_payment"])
    return model, categories


def method_scores(df: pd.DataFrame, probability: np.ndarray) -> dict:
    return {
        "biggest_order": df["order_value_rs"].to_numpy(),
        "lightgbm": probability,
        "expected_loss": probability * df["paid_rs"].to_numpy(),
    }


def capture(df: pd.DataFrame, scores, share: float) -> dict:
    """Money and cancellations caught when the top `share` of orders by score are reviewed."""
    n = max(1, int(round(len(df) * share)))
    top = df.assign(score=scores).nlargest(n, "score")
    return {"orders_reviewed": n,
            "money_caught": float(top["at_risk_rs"].sum() / df["at_risk_rs"].sum()),
            "cancels_caught": float(top["canceled_after_payment"].sum() / df["canceled_after_payment"].sum())}


def evaluate(df: pd.DataFrame, probability: np.ndarray, share: float, period: str) -> list[dict]:
    from sklearn.metrics import average_precision_score

    rows = [{"period": period, "method": "random", "orders_reviewed": max(1, int(round(len(df) * share))),
             "money_caught": share, "cancels_caught": share}]
    for method, scores in method_scores(df, probability).items():
        rows.append({"period": period, "method": method, **capture(df, scores, share)})
    for row in rows:
        row["pr_auc"] = (float(average_precision_score(df["canceled_after_payment"], probability))
                         if row["method"] == "lightgbm" else np.nan)
    return rows


def calibration(df: pd.DataFrame, probability: np.ndarray, bins: int = 5) -> pd.DataFrame:
    """Predicted vs actual cancellations in groups from lowest to highest predicted chance."""
    groups = pd.qcut(pd.Series(probability).rank(method="first"), bins, labels=False)
    out = pd.DataFrame({"group": groups.to_numpy() + 1, "predicted": probability,
                        "actual": df["canceled_after_payment"].to_numpy()})
    return out.groupby("group").agg(orders=("actual", "size"), predicted_cancels=("predicted", "sum"),
                                    actual_cancels=("actual", "sum")).reset_index()



def select_winner(tuning: pd.Series, tie_break: list[str]) -> tuple[str, list[str]]:
    """Best method on the tuning months. Ties go to the method listed first in tie_break.

    Returns the winner and every method that tied for first place.
    """
    best = tuning.max()
    tied = [m for m in tuning.index if np.isclose(tuning[m], best)]
    winner = next(m for m in tie_break if m in tied) if len(tied) > 1 else tied[0]
    return winner, tied


def walk_forward_capture(orders: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Money caught by each method in every month before the holdout, as if run live that month.

    For each month M the model is trained only on orders bought before M minus settle_days (their
    outcome would be known by then), then ranks the orders of month M. One 3-month tuning block held
    too few cancellations: the vote was decided by one or two orders and flipped on the holdout.
    Nine monthly windows count far more cancellations before anything is chosen.
    """
    when = orders["purchased_at"]
    share = cfg["review_share"]
    gap = pd.Timedelta(days=cfg["settle_days"])
    rows = []
    for month in pd.date_range(cfg["selection_start"], cfg["tuning_end"], freq="MS", inclusive="left"):
        train = orders[(when >= cfg["train_start"]) & (when < month - gap)]
        test = orders[(when >= month) & (when < month + pd.offsets.MonthBegin(1))]
        if test["at_risk_rs"].sum() == 0:
            continue                                   # nothing at risk that month: nothing to compare
        model, categories = train_model(train, cfg)
        prob = model.predict_proba(model_inputs(test, cfg, categories))[:, 1]
        for method, scores in method_scores(test, prob).items():
            rows.append({"window": month.strftime("%Y-%m"), "method": method,
                         "cancels_in_window": int(test["canceled_after_payment"].sum()),
                         **capture(test, scores, share)})
    return pd.DataFrame(rows)


def choose_method(windows: pd.DataFrame, baseline: str, min_win_share: float, min_margin: float) -> dict:
    """Keep the simple baseline unless a model method clearly beats it, window after window.

    A model method replaces the baseline only if it beats it in at least `min_win_share` of the
    windows AND its median lead is at least `min_margin` (share of money at risk). Written down
    before rerunning, so the holdout result cannot change the rule.
    """
    table = windows.pivot(index="window", columns="method", values="money_caught")
    report = {}
    for method in [m for m in table.columns if m != baseline]:
        lead = table[method] - table[baseline]
        report[method] = {"win_share": float((lead > 0).mean()), "median_lead": float(lead.median()),
                          "passes": bool((lead > 0).mean() >= min_win_share and lead.median() >= min_margin)}
    passing = [m for m, r in report.items() if r["passes"]]
    winner = max(passing, key=lambda m: report[m]["median_lead"]) if passing else baseline
    return {"winner": winner, "baseline": baseline, "windows": int(len(table)),
            "median_money_caught": {m: float(v) for m, v in table.median().items()}, "challengers": report}


def score_column(method: str) -> str:
    """Which column of the scored orders ranks the queue for each method."""
    return {"expected_loss": "expected_loss_rs", "lightgbm": "chance", "biggest_order": "paid_rs"}[method]


def bootstrap_capture(df: pd.DataFrame, scores: dict, share: float, samples: int, seed: int) -> pd.DataFrame:
    """Money caught by the top `share` of orders, on `samples` reshuffled copies of df.

    Each copy draws len(df) orders at random WITH replacement, so some orders appear twice and
    some not at all. How much the result moves between copies shows how much of it is luck.
    """
    rng = np.random.default_rng(seed)
    money = df["at_risk_rs"].to_numpy()
    n = len(df)
    k = max(1, int(round(n * share)))
    rows = []
    for _ in range(samples):
        idx = rng.integers(0, n, n)
        total = money[idx].sum()
        row = {}
        for method, s in scores.items():
            top = np.argpartition(-np.asarray(s)[idx], k - 1)[:k]
            row[method] = money[idx][top].sum() / total if total else np.nan
        rows.append(row)
    return pd.DataFrame(rows)



def prepare(orders: pd.DataFrame, cfg: dict) -> dict:
    """Parse dates, add point-in-time seller history and split into train / tuning / holdout."""
    orders = orders.copy()
    orders["purchased_at"] = pd.to_datetime(orders["purchased_at"])
    train_mask = (orders["purchased_at"] >= cfg["train_start"]) & (orders["purchased_at"] < cfg["train_end"])
    prior = orders.loc[train_mask, "canceled_after_payment"].mean()
    return split(add_seller_history(orders, cfg["settle_days"], cfg["smoothing_strength"], prior), cfg)