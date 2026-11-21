"""
How stable is the checkout queue? Retrain the same model with 20 different random seeds (Phase 6 audit).

Why: the dashboard showed the 1% queue catching 1.4% of the money at risk, while the Phase 4.8 run
caught 35.6%. The only difference was the row order of the mart (Athena rewrites it on every rebuild),
and LightGBM's bagging picks rows by position. If a harmless change like that moves the result from
35% to 1%, the 35.6% was partly luck, and we should report the range, not one number.

The seed plays the same role as the row order: it only changes which rows each tree samples.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/check_order_risk_stability.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.athena_tools import read_table  # noqa: E402
from src.ml.order_risk import capture, method_scores, model_inputs, prepare, train_model  # noqa: E402

CONFIG_FILE = REPO_ROOT / "config" / "ml.yaml"
SEEDS = range(20)


def main() -> None:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))["order_risk"]
    parts = prepare(read_table(cfg["source_table"]), cfg)
    holdout, share = parts["holdout"], cfg["review_share"]

    rows = []
    for seed in SEEDS:
        model, categories = train_model(parts["train"], cfg, seed=seed)
        prob = model.predict_proba(model_inputs(holdout, cfg, categories))[:, 1]
        for method, scores in method_scores(holdout, prob).items():
            rows.append({"seed": seed, "method": method, **capture(holdout, scores, share)})
    results = pd.DataFrame(rows)

    summary = results.groupby("method")["money_caught"].describe(percentiles=[0.1, 0.5, 0.9])
    summary = summary[["min", "10%", "50%", "90%", "max"]].mul(100).round(1)
    print(f"Top {share:.0%} queue on unseen months (Apr to Jul 2018), money caught in %, over {len(SEEDS)} seeds:")
    print(summary.to_string())

    cancels = results.groupby("method")["cancels_caught"].median().mul(100).round(1)
    print("\nMedian share of cancellations caught (%):")
    print(cancels.to_string())
    print("\nbiggest_order does not use the model, so its row should not move at all (a built-in sanity check).")


if __name__ == "__main__":
    main()
