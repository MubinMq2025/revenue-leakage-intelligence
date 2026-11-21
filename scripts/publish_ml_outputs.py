"""
Publish the Phase 4 model outputs to S3 / Athena (Phase 4.6).

Reads what the earlier scripts saved in data/output/, shapes five tables (config/ml_tables.yaml)
and writes each one as Parquet to the S3 location its Glue table points at:

    ml_seller_queue          every active seller at the latest snapshot, ranked by the chosen method
    ml_seller_risk_backtest  the seller queue backtest
    ml_revenue_forecast      forecast backtest plus the next 4 weeks
    ml_order_risk            checkout risk scores, the review queue and its reasons
    ml_drift_checks          the latest drift report, one row per check

Run after: build_seller_features, backtest_seller_risk, backtest_forecast, check_drift,
backtest_order_risk, explain_order_risk. Needs terraform apply first (the tables must exist).

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/publish_ml_outputs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import DATABASE, REGION  # noqa: E402
from src.ml.forecast import select_method as select_forecast  # noqa: E402
from src.ml.forecast import summarize  # noqa: E402
from src.ml.order_risk import score_column  # noqa: E402
from src.ml.publish import publish  # noqa: E402
from src.ml.seller_risk import method_scores, select_method, training_snapshots  # noqa: E402

OUTPUT = REPO_ROOT / "data" / "output"
ML_CONFIG = REPO_ROOT / "config" / "ml.yaml"
TABLES_CONFIG = REPO_ROOT / "config" / "ml_tables.yaml"


def seller_queue(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    risk = cfg["seller_risk"]
    features = pd.read_parquet(OUTPUT / "seller_features.parquet")
    backtest = pd.read_csv(OUTPUT / "seller_risk_backtest.csv", parse_dates=["snapshot"])
    method, _ = select_method(backtest, risk["selection"]["tuning_end"], risk["review_queue_size"])

    snapshots = sorted(features["snapshot"].unique())
    latest = pd.Timestamp(snapshots[-1])
    snap = features[features["snapshot"] == latest].reset_index(drop=True)
    train = features[features["snapshot"].isin(training_snapshots(snapshots, latest, cfg["seller_features"]["horizon_months"]))]
    score = pd.Series(method_scores(train, snap, risk)[method])
    snap = snap.assign(method=method, queue_rank=score.rank(ascending=False, method="first").astype(int))
    snap["in_queue"] = (snap["queue_rank"] <= risk["review_queue_size"]).astype(int)
    return snap.sort_values("queue_rank"), backtest


def revenue_forecast(cfg: dict) -> pd.DataFrame:
    fc = cfg["revenue_forecast"]
    backtest = pd.read_csv(OUTPUT / "revenue_forecast_backtest.csv", parse_dates=["origin", "target_week"])
    future = pd.read_csv(OUTPUT / "revenue_forecast_future.csv", parse_dates=["origin", "target_week"])
    chosen = select_forecast(summarize(backtest, fc["tuning_end"], fc["black_friday_weeks"]))
    rows = pd.concat([backtest.assign(kind="backtest"), future.assign(kind="future", actual=float("nan"))])
    return rows.assign(is_chosen=(rows["method"] == chosen).astype(int))


def order_risk(cfg: dict) -> pd.DataFrame:
    orc = cfg["order_risk"]
    scores = pd.read_parquet(OUTPUT / "order_risk_scores.parquet")
    reasons = pd.read_csv(OUTPUT / "order_risk_queue_reasons.csv", dtype={"order_id": str})[["order_id", "reasons"]]
    # The method chosen by the backtest on the median over seeds (not re-decided here from one run)
    method = json.loads((OUTPUT / "order_risk_winner.json").read_text(encoding="utf-8"))["winner"]
    score_col = score_column(method)

    out = scores.rename(columns={"probability": "chance"}).astype({"order_id": str})
    out = out.merge(reasons, on="order_id", how="left")
    out["queue_rank"] = out[score_col].rank(ascending=False, method="first").astype(int)
    out["in_queue"] = (out["queue_rank"] <= max(1, round(len(out) * orc["review_share"]))).astype(int)
    out.loc[out["in_queue"] == 0, "queue_rank"] = None
    return out.sort_values("queue_rank")


def drift_checks() -> pd.DataFrame:
    report = json.loads((OUTPUT / "drift_report.json").read_text(encoding="utf-8"))
    rows = []
    for r in report["feature_drift"]:
        rows.append({"check_group": "size_and_price", "name": r["feature"], "value": r["psi"], "status": r["status"],
                     "detail": f"PSI; median {r['reference_median']:.3g} -> {r['current_median']:.3g}"})
    for r in report["rate_drift"]:
        rows.append({"check_group": "behaviour", "name": r["rate"], "value": r["change"], "status": r["status"],
                     "detail": f"relative change; {r['before']:.2%} -> {r['after']:.2%}"})
    for r in report["performance"]:
        rows.append({"check_group": "performance", "name": r["check"], "value": r["ratio"], "status": r["status"],
                     "detail": f"recent / early; {r['early']:.3f} -> {r['recent']:.3f}"})
    return pd.DataFrame(rows).assign(checked_at=report["checked_at"], overall_status=report["status"])


def main() -> None:
    cfg = yaml.safe_load(ML_CONFIG.read_text(encoding="utf-8"))
    specs = yaml.safe_load(TABLES_CONFIG.read_text(encoding="utf-8"))["tables"]

    queue, queue_backtest = seller_queue(cfg)
    frames = {
        "ml_seller_queue": queue,
        "ml_seller_risk_backtest": queue_backtest,
        "ml_revenue_forecast": revenue_forecast(cfg),
        "ml_order_risk": order_risk(cfg),
        "ml_drift_checks": drift_checks(),
    }

    session = boto3.Session(region_name=REGION)
    glue, s3 = session.client("glue"), session.client("s3")
    for table, df in frames.items():
        key = publish(df, table, specs[table]["columns"], glue, s3, DATABASE)
        print(f"OK      {table:<26} {len(df):>7,} rows  -> s3://.../{key}")
    print(f"\nAll {len(frames)} ML tables published to {DATABASE}")


if __name__ == "__main__":
    main()