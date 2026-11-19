"""
Explain the checkout risk model in plain English (Phase 4.8c).

Loads the model saved by scripts/backtest_order_risk.py, computes SHAP contributions for the
unseen months (Apr to Jul 2018), and prints:
    1. which inputs matter most overall
    2. your two ideas, with everything else held equal: order size and delivery share of price
    3. the 10 orders the queue would check first, each with its top 3 reasons
Saves the reasons for the whole review queue (top 1% by expected loss) for the dashboard.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/explain_order_risk.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import read_table  # noqa: E402
from src.ml.explain import contributions, importance, top_reasons  # noqa: E402
from src.ml.order_risk import model_inputs, prepare  # noqa: E402
from src.ml.tracking import log_run  # noqa: E402

CONFIG_FILE = REPO_ROOT / "config" / "ml.yaml"
OUTPUT = REPO_ROOT / "data" / "output"
MODEL_FILE = OUTPUT / "order_risk_model.txt"
SCORES_FILE = OUTPUT / "order_risk_scores.parquet"
REASONS_FILE = OUTPUT / "order_risk_queue_reasons.csv"


def effect_by_band(values: pd.Series, contrib: pd.Series, bands: int = 5) -> pd.DataFrame:
    """Average push on the risk for each band of an input, everything else held as it was."""
    band = pd.qcut(values.rank(method="first"), bands, labels=False) + 1
    out = pd.DataFrame({"band": band, "value": values, "push": contrib}).groupby("band").agg(
        from_value=("value", "min"), to_value=("value", "max"), average_push=("push", "mean"))
    out["chance_vs_average"] = np.exp(out["average_push"])   # log-odds push -> roughly "x times the chance"
    return out.reset_index()


def main() -> None:
    import lightgbm as lgb

    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))["order_risk"]
    holdout = prepare(read_table(cfg["source_table"]), cfg)["holdout"]
    booster = lgb.Booster(model_file=str(MODEL_FILE))
    x = model_inputs(holdout, cfg)
    chance = booster.predict(x)

    # Safety check: the saved model must give the same chances as the backtest did
    saved = pd.read_parquet(SCORES_FILE).set_index("order_id")["probability"]
    gap = np.abs(saved.reindex(holdout["order_id"]).to_numpy() - chance).max()
    print(f"Model reloaded: largest difference from the backtest's scores = {gap:.1e} (should be about 0)")

    contrib = contributions(booster, x)
    imp = importance(contrib)
    print(f"\n1. What drives the chance of cancellation (unseen months, {len(holdout):,} orders):")
    print((imp / imp.sum() * 100).round(1).astype(str).add("%").head(10).to_string())

    print("\n2. Your ideas, everything else held equal (1.00x = no effect, 2.00x = about double the chance):")
    for feature, label in (("order_value_rs", "Order size (R$)"), ("freight_ratio", "Delivery as share of price")):
        table = effect_by_band(holdout[feature], contrib[feature])
        print(f"\n{label}:")
        print(table.assign(from_value=table["from_value"].round(2), to_value=table["to_value"].round(2),
                           chance_vs_average=table["chance_vs_average"].map("{:.2f}x".format))
              .drop(columns="average_push").to_string(index=False))

    # The review queue: top 1% by expected loss (chance x amount paid), with reasons
    queue = holdout.assign(chance=chance, expected_loss_rs=chance * holdout["paid_rs"])
    n = max(1, int(round(len(queue) * cfg["review_share"])))
    queue = queue.nlargest(n, "expected_loss_rs")
    reasons = {i: top_reasons(contrib.loc[i], holdout.loc[i, cfg["numeric_features"] + cfg["categorical_features"]])
               for i in queue.index}
    queue["reasons"] = [" | ".join(reasons[i]) for i in queue.index]

    print(f"\n3. First 10 of the {n} orders the queue would check (unseen months):")
    for _, r in queue.head(10).iterrows():
        outcome = "CANCELLED after payment" if r["canceled_after_payment"] else "went through"
        print(f"  R${r['paid_rs']:>8,.0f} paid, {r['chance']:.1%} chance, R${r['expected_loss_rs']:,.0f} expected at risk"
              f" -> {outcome}\n      why: {r['reasons']}")

    caught = queue["canceled_after_payment"].sum()
    print(f"\nThe queue of {n} orders contains {int(caught)} of the {int(holdout['canceled_after_payment'].sum())} "
          f"cancellations and R${queue['at_risk_rs'].sum():,.0f} of the R${holdout['at_risk_rs'].sum():,.0f} at risk")

    queue[["order_id", "purchased_at", "main_seller_id", "paid_rs", "chance", "expected_loss_rs", "reasons",
           "canceled_after_payment", "at_risk_rs"]].to_csv(REASONS_FILE, index=False)
    print(f"Saved {REASONS_FILE.relative_to(REPO_ROOT)}")

    metrics = {f"importance.{f}": float(v) for f, v in (imp / imp.sum()).items()}
    metrics["queue_cancels_caught"] = float(caught)
    run_id = log_run("order_risk", f"explain {pd.Timestamp.now():%Y-%m-%d %H:%M}", params={"review_share": cfg["review_share"]},
                     metrics=metrics, artifacts=[REASONS_FILE], tags={"step": "4.8c explanations"})
    print(f"Logged to MLflow (experiment order_risk, run {run_id[:8]})")


if __name__ == "__main__":
    main()