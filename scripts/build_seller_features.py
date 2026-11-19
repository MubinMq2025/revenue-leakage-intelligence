"""
Build the point-in-time seller feature table (Phase 4.1) and save it to data/output/.

Reads mart_seller_orders from S3, builds one snapshot per month (config/ml.yaml), and prints
a short summary so the result can be checked by eye.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/build_seller_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import read_table  # noqa: E402
from src.ml.features import build_features, hidden_delivery_share  # noqa: E402

CONFIG_FILE = REPO_ROOT / "config" / "ml.yaml"
OUTPUT_FILE = REPO_ROOT / "data" / "output" / "seller_features.parquet"
WATCH_SELLER = "c4f7fee5b0db50e87766f5a4d1b1b758"   # the 76.7% seller from Phase 3


def main() -> None:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))["seller_features"]

    orders = read_table(cfg["source_table"])
    for col in ("purchase_month", "delivered_date"):
        orders[col] = pd.to_datetime(orders[col])
    print(f"Read {len(orders):,} order-seller rows from {cfg['source_table']}")

    features = build_features(orders, cfg)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT_FILE, index=False)

    per_snapshot = features.groupby("snapshot").size()
    print(f"Built {len(features):,} rows: {len(per_snapshot)} snapshots, "
          f"{per_snapshot.min():,} to {per_snapshot.max():,} active sellers each")
    print(f"Deliveries hidden because they happened after the snapshot: {hidden_delivery_share(orders, cfg):.1%}")
    print(f"Saved to {OUTPUT_FILE.relative_to(REPO_ROOT)}")

    pd.set_option("display.width", 160)
    latest = features[features["snapshot"] == features["snapshot"].max()]
    print(f"\nTop 10 sellers by smoothed at-risk rate at {latest['snapshot'].iloc[0]:%Y-%m-%d}:")
    print(latest.nlargest(10, "at_risk_rate")[
        ["seller_id", "orders", "revenue_rs", "at_risk_rate", "cancel_rate", "avg_review", "future_at_risk_rs"]
    ].round(3).to_string(index=False))

    watch = features[features["seller_id"] == WATCH_SELLER]
    print(f"\nSeller {WATCH_SELLER[:8]} over time (features as known at each snapshot):")
    print(watch[["snapshot", "orders", "at_risk_rate", "cancel_rate", "avg_review", "future_at_risk_rs"]]
          .round(3).to_string(index=False))


if __name__ == "__main__":
    main()