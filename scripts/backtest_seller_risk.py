"""
Backtest the seller risk rankings (Phase 4.2).

For every test month: rank the sellers with each method, take the top of the queue, and measure
what share of the next 3 months' seller-attributable money at risk those sellers caused.
Run scripts/build_seller_features.py first.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/backtest_seller_risk.py

The winner is chosen on the tuning months only, then confirmed on the holdout months (config/ml.yaml).
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import pandas as pd
import yaml

matplotlib.use("Agg")  # save charts to files, no window
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import read_table  # noqa: E402
from src.ml.features import hidden_delivery_share, windows  # noqa: E402
from src.ml.seller_risk import METHODS, backtest, method_scores, select_method, training_snapshots  # noqa: E402

CONFIG_FILE = REPO_ROOT / "config" / "ml.yaml"
FEATURES_FILE = REPO_ROOT / "data" / "output" / "seller_features.parquet"
RESULTS_FILE = REPO_ROOT / "data" / "output" / "seller_risk_backtest.csv"
CHART_FILE = REPO_ROOT / "docs" / "images" / "seller_risk_gains.png"
WATCH_SELLER = "c4f7fee5b0db50e87766f5a4d1b1b758"


def print_watch_seller_ranks(features: pd.DataFrame, cfg: dict, fcfg: dict) -> None:
    """Rank of the Phase 3 seller in each method's queue at its last snapshot before the losses."""
    t = pd.Timestamp(features.loc[features["seller_id"] == WATCH_SELLER, "snapshot"].max())
    snap = features[features["snapshot"] == t].reset_index(drop=True)
    train = features[features["snapshot"].isin(training_snapshots(sorted(features["snapshot"].unique()), t, fcfg["horizon_months"]))]
    ranks = {m: pd.Series(s).rank(ascending=False) for m, s in method_scores(train, snap, cfg).items()}
    row = snap.index[snap["seller_id"] == WATCH_SELLER][0]
    print(f"\nSeller {WATCH_SELLER[:8]} rank at {t:%Y-%m} out of {len(snap):,} sellers:")
    for method, rank in ranks.items():
        print(f"  {method:<22} #{int(rank[row]):,}")


def main() -> None:
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    fcfg, cfg = config["seller_features"], config["seller_risk"]
    k = cfg["review_queue_size"]

    features = pd.read_parquet(FEATURES_FILE)
    orders = read_table(fcfg["source_table"])
    for col in ("purchase_month", "delivered_date"):
        orders[col] = pd.to_datetime(orders[col])
    context = [f"Features: {len(features):,} seller-months. Deliveries hidden as not yet known: "
               f"{hidden_delivery_share(orders, fcfg):.1%}"]

    # All seller-attributable money at risk in each label window, including sellers with no history yet
    totals, new_share = {}, {}
    for t in sorted(features["snapshot"].unique()):
        w = windows(t, fcfg)
        future = orders[(orders["purchase_month"] >= w["snapshot"]) & (orders["purchase_month"] < w["label_end"])]
        known = set(features.loc[features["snapshot"] == t, "seller_id"])
        totals[pd.Timestamp(t)] = future["at_risk_rs"].sum()
        new_share[pd.Timestamp(t)] = future.loc[~future["seller_id"].isin(known), "at_risk_rs"].sum() / totals[pd.Timestamp(t)]

    results = backtest(features, totals, cfg, fcfg["horizon_months"])
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(RESULTS_FILE, index=False)

    tests = sorted(results["snapshot"].unique())
    context.append(f"Test months: {pd.Timestamp(tests[0]):%Y-%m} to {pd.Timestamp(tests[-1]):%Y-%m} ({len(tests)} months)")
    context.append(f"Future risk from sellers with no history yet (no model can rank them): "
                   f"{sum(new_share[pd.Timestamp(t)] for t in tests) / len(tests):.1%} on average")

    gains = results.pivot_table(index="k", columns="method", values="capture", aggfunc="mean")[METHODS]
    print("\nAverage share of next-3-month seller risk caught by the top k sellers:")
    print((gains * 100).round(1).astype(str).add("%").to_string())

    at_k = results[results["k"] == k].pivot(index="snapshot", columns="method", values="capture")[METHODS]
    at_k.index = [f"{pd.Timestamp(s):%Y-%m}" for s in at_k.index]
    print(f"\nTop {k} queue, month by month:")
    print((at_k * 100).round(1).astype(str).add("%").to_string())

    tuning_end = cfg["selection"]["tuning_end"]
    winner, table = select_method(results, tuning_end, k)
    print(f"\nModel selection, top {k} queue (winner picked on tuning months only):")
    print((table * 100).round(1).astype(str).add("%").to_string())
    print(f"Winner: {winner}. Its honest result on unseen months: {table.loc[winner, 'holdout']:.1%} "
          f"(random: {results[(results['k'] == k) & (results['method'] == 'random') & (results['snapshot'] >= pd.Timestamp(tuning_end))]['capture'].mean():.1%})")

    # Where would the c4f7fee5 seller have been in each queue just before its losses?
    if WATCH_SELLER not in set(features["seller_id"]):
        print(f"\nSeller {WATCH_SELLER[:8]} has no snapshot in the feature table")
    else:
        print_watch_seller_ranks(features, cfg, fcfg)

    CHART_FILE.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for method in METHODS:
        ax.plot(gains.index, gains[method] * 100, marker="o", label=method)
    ax.axvline(k, color="grey", linestyle="--", linewidth=1)
    ax.set(xscale="log", xlabel="Sellers reviewed per month (log scale)",
           ylabel="Share of next-3-month seller risk caught (%)", title="Seller risk ranking: backtest gains")
    ax.legend()
    fig.tight_layout()
    fig.savefig(CHART_FILE, dpi=150)
    print(f"\nSaved {RESULTS_FILE.relative_to(REPO_ROOT)} and {CHART_FILE.relative_to(REPO_ROOT)}")
    print("\nContext:")
    for line in context:
        print(f"  {line}")


if __name__ == "__main__":
    main()