"""
Train and backtest the checkout risk model (Phase 4.8b).

Trains LightGBM on 2017 orders, scores Jan to Mar 2018 (to pick the best ranking method) and
Apr to Jul 2018 (unseen, the honest test), and compares with simple rules. Finance reviews the
top 1% of orders; the score is the share of money at risk those orders contain.

4.8b+: every holdout number also gets a likely range (bootstrap).
Phase 6: the method is chosen on monthly walk-forward windows before the holdout, and the simple
"biggest order first" rule stays unless a model clearly beats it (choose_method in src/ml/order_risk.py).

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/backtest_order_risk.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")  # save charts to files, no window
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import read_table  # noqa: E402
from src.ml.order_risk import (METHODS, add_seller_history, bootstrap_capture, calibration, capture,  # noqa: E402
                               choose_method, evaluate, method_scores, model_inputs, split, train_model, walk_forward_capture)
from src.ml.tracking import log_run  # noqa: E402

CONFIG_FILE = REPO_ROOT / "config" / "ml.yaml"
OUTPUT = REPO_ROOT / "data" / "output"
RESULTS_FILE = OUTPUT / "order_risk_backtest.csv"
SCORES_FILE = OUTPUT / "order_risk_scores.parquet"
WINNER_FILE = OUTPUT / "order_risk_winner.json"   # read by explain_order_risk.py and publish_ml_outputs.py
MODEL_FILE = OUTPUT / "order_risk_model.txt"
CHART_FILE = REPO_ROOT / "docs" / "images" / "order_risk_gains.png"


def main() -> None:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))["order_risk"]

    orders = read_table(cfg["source_table"])
    orders["purchased_at"] = pd.to_datetime(orders["purchased_at"])
    train_mask = (orders["purchased_at"] >= cfg["train_start"]) & (orders["purchased_at"] < cfg["train_end"])
    prior = orders.loc[train_mask, "canceled_after_payment"].mean()
    orders = add_seller_history(orders, cfg["settle_days"], cfg["smoothing_strength"], prior)
    parts = split(orders, cfg)
    for name, part in parts.items():
        print(f"{name:<8} {len(part):>6,} orders, {int(part['canceled_after_payment'].sum()):>3} cancelled after payment "
              f"({part['canceled_after_payment'].mean():.2%}), R${part['at_risk_rs'].sum():,.0f} at risk")

    model, categories = train_model(parts["train"], cfg)
    share = cfg["review_share"]
    rows, probs = [], {}
    for period in ("tuning", "holdout"):
        part = parts[period]
        probs[period] = model.predict_proba(model_inputs(part, cfg, categories))[:, 1]
        rows += evaluate(part, probs[period], share, period)
    results = pd.DataFrame(rows)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results.to_csv(RESULTS_FILE, index=False)

    table = results.pivot(index="method", columns="period", values="money_caught")[["tuning", "holdout"]].loc[METHODS]
    cancels = results.pivot(index="method", columns="period", values="cancels_caught")["holdout"].loc[METHODS]
    print(f"\nReviewing the top {share:.0%} of orders, share of money at risk caught:")
    shown = pd.DataFrame({"tuning (Jan to Mar 2018)": table["tuning"], "holdout (Apr to Jul 2018)": table["holdout"],
                          "holdout cancels caught": cancels})
    print((shown * 100).round(1).astype(str).add("%").to_string())

    # Choose on monthly walk-forward windows, simple rule unless a model clearly wins (see choose_method)
    windows = walk_forward_capture(orders, cfg)
    choice = choose_method(windows, cfg["selection_baseline"], cfg["min_win_share"], cfg["min_margin"])
    print(f"\nWalk-forward windows ({choice['windows']} months before the holdout, "
          f"{windows.drop_duplicates('window')['cancels_in_window'].sum()} cancellations), money caught per month:")
    print((windows.pivot(index="window", columns="method", values="money_caught") * 100).round(1).to_string())
    for method, r in choice["challengers"].items():
        print(f"  {method:<14} beats {choice['baseline']} in {r['win_share']:.0%} of months, "
              f"median lead {r['median_lead'] * 100:+.1f} pts -> {'PASSES' if r['passes'] else 'does not pass'}")
    winner = choice["winner"]
    WINNER_FILE.write_text(json.dumps(choice, indent=2))
    windows.to_csv(OUTPUT / "order_risk_walk_forward.csv", index=False)
    pr_auc = results.loc[(results["method"] == "lightgbm") & (results["period"] == "holdout"), "pr_auc"].item()
    base = parts["holdout"]["canceled_after_payment"].mean()
    print(f"\nWinner (picked on months before the holdout only): {winner}. Honest result on unseen months: "
          f"{table.loc[winner, 'holdout']:.1%} of money at risk from {share:.0%} of orders")
    print(f"LightGBM PR-AUC on unseen months: {pr_auc:.3f} (random would score {base:.3f}, "
          f"so {pr_auc / base:.1f}x better than chance)")

    # How sure can we be? Re-score 1,000 reshuffled copies of the unseen orders
    boot = bootstrap_capture(parts["holdout"], method_scores(parts["holdout"], probs["holdout"]), share,
                             cfg["bootstrap_samples"], cfg["random_state"])
    tail = (1 - cfg["interval"]) / 2
    ranges = pd.DataFrame({"result": table["holdout"].drop(index="random"),
                           "likely_low": boot.quantile(tail), "likely_high": boot.quantile(1 - tail)})
    print(f"\nHow sure? Unseen months, top {share:.0%}, {cfg['interval']:.0%} range from "
          f"{cfg['bootstrap_samples']:,} reshuffled copies:")
    print((ranges * 100).round(1).astype(str).add("%").to_string())
    beats = {m: float((boot[m] > boot["biggest_order"]).mean()) for m in boot.columns if m != "biggest_order"}
    for m, p in beats.items():
        print(f"  {m} caught more money than biggest_order in {p:.0%} of the copies")

    cal = calibration(parts["holdout"], probs["holdout"])
    print("\nCalibration on unseen months (does a 1% chance really mean about 1 in 100?):")
    print(cal.assign(predicted_cancels=cal["predicted_cancels"].round(1)).to_string(index=False))

    holdout = parts["holdout"].assign(probability=probs["holdout"],
                                      expected_loss_rs=probs["holdout"] * parts["holdout"]["paid_rs"])
    holdout[["order_id", "purchased_at", "main_seller_id", "paid_rs", "probability", "expected_loss_rs",
             "canceled_after_payment", "at_risk_rs"]].to_parquet(SCORES_FILE, index=False)
    model.booster_.save_model(str(MODEL_FILE))

    # Gains chart on unseen months: share of money caught as finance reviews more orders
    shares = [0.005, 0.01, 0.02, 0.05, 0.10, 0.20]
    scores = method_scores(holdout, probs["holdout"])
    CHART_FILE.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot([s * 100 for s in shares], [s * 100 for s in shares], marker="o", label="random")
    for method, s in scores.items():
        ax.plot([x * 100 for x in shares], [capture(holdout, s, x)["money_caught"] * 100 for x in shares],
                marker="o", label=method)
    ax.axvline(share * 100, color="grey", linestyle="--", linewidth=1)
    ax.set(xscale="log", xlabel="Orders reviewed (% of all orders, log scale)",
           ylabel="Money at risk caught (%)", title="Checkout risk: gains on unseen months (Apr to Jul 2018)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(CHART_FILE, dpi=150)
    print(f"\nSaved {RESULTS_FILE.relative_to(REPO_ROOT)}, {SCORES_FILE.relative_to(REPO_ROOT)}, "
          f"{MODEL_FILE.relative_to(REPO_ROOT)} and {CHART_FILE.relative_to(REPO_ROOT)}")

    metrics = {f"money_caught_top{share * 100:g}pct.{p}.{m}": table.loc[m, p] for m in METHODS for p in ("tuning", "holdout")}
    metrics.update({f"holdout_low.{m}": ranges.loc[m, "likely_low"] for m in ranges.index})
    metrics.update({f"holdout_high.{m}": ranges.loc[m, "likely_high"] for m in ranges.index})
    metrics.update({f"beats_biggest_order.{m}": p for m, p in beats.items()})
    metrics.update({"pr_auc_holdout": pr_auc, "holdout_base_rate": base,
                    "holdout_predicted_cancels": float(np.sum(probs["holdout"])),
                    "holdout_actual_cancels": float(parts["holdout"]["canceled_after_payment"].sum())})
    run_id = log_run("order_risk", f"backtest {pd.Timestamp.now():%Y-%m-%d %H:%M}", params=cfg, metrics=metrics,
                     artifacts=[CHART_FILE, RESULTS_FILE], tags={"winner": winner})
    print(f"Logged to MLflow (experiment order_risk, run {run_id[:8]})")


if __name__ == "__main__":
    main()