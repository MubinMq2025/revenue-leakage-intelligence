"""
Check for drift (Phase 4.5b) and write a report that Phase 5 can turn into an alert.

Reads mart_seller_orders from S3 plus the outputs of the earlier steps:
    data/output/seller_features.parquet       (scripts/build_seller_features.py)
    data/output/seller_risk_backtest.csv      (scripts/backtest_seller_risk.py)
    data/output/revenue_forecast_backtest.csv (scripts/backtest_forecast.py)
Writes data/output/drift_report.json and logs the run to MLflow.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/check_drift.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import read_table  # noqa: E402
from src.ml.drift import feature_drift, forecast_decay, overall_status, rate_drift, seller_queue_decay  # noqa: E402
from src.ml.forecast import select_method as select_forecast  # noqa: E402
from src.ml.forecast import summarize, wape  # noqa: E402
from src.ml.seller_risk import select_method as select_queue  # noqa: E402
from src.ml.tracking import log_run  # noqa: E402

CONFIG_FILE = REPO_ROOT / "config" / "ml.yaml"
OUTPUT = REPO_ROOT / "data" / "output"
REPORT_FILE = OUTPUT / "drift_report.json"


def main() -> None:
    config = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    cfg, risk_cfg, fc_cfg = config["drift"], config["seller_risk"], config["revenue_forecast"]

    features = pd.read_parquet(OUTPUT / "seller_features.parquet")
    queue = pd.read_csv(OUTPUT / "seller_risk_backtest.csv", parse_dates=["snapshot"])
    forecast = pd.read_csv(OUTPUT / "revenue_forecast_backtest.csv", parse_dates=["origin", "target_week"])

    orders = read_table(config["seller_features"]["source_table"])
    orders["purchase_month"] = pd.to_datetime(orders["purchase_month"])

    # 1. Size and price drift: did the sellers change shape?
    drift = feature_drift(features, cfg)
    print(f"Size and price drift (PSI), {cfg['reference_snapshots'][0][:7]} to {cfg['reference_snapshots'][-1][:7]} "
          f"vs {cfg['current_snapshots'][0][:7]} to {cfg['current_snapshots'][-1][:7]}:")
    print(f"  under {cfg['psi_watch']} = OK, {cfg['psi_watch']} to {cfg['psi_alert']} = WATCH, "
          f"over {cfg['psi_alert']} = ALERT\n")
    print(drift.round(3).to_string(index=False))

    # 2. Behaviour drift: did overall cancel, late, review and at-risk rates change?
    rates = rate_drift(orders, cfg)
    print(f"\nBehaviour drift, overall rates {cfg['reference_months'][0][:7]} to {cfg['reference_months'][-1][:7]} "
          f"vs {cfg['current_months'][0][:7]} to {cfg['current_months'][-1][:7]} "
          f"(WATCH over {cfg['rate_watch']:.0%} change, ALERT over {cfg['rate_alert']:.0%}):")
    shown = rates.assign(before=rates["before"].map("{:.2%}".format), after=rates["after"].map("{:.2%}".format),
                         change=rates["change"].map("{:+.0%}".format))
    print(shown.to_string(index=False))

    # 3. Performance decay of the methods we actually chose
    k = risk_cfg["review_queue_size"]
    queue_method, _ = select_queue(queue, risk_cfg["selection"]["tuning_end"], k)
    fc_method = select_forecast(summarize(forecast, fc_cfg["tuning_end"], fc_cfg["black_friday_weeks"]))
    checks = [seller_queue_decay(queue, queue_method, k, cfg), forecast_decay(forecast, fc_method, cfg, wape)]
    print("\nPerformance decay of the chosen methods:")
    print(pd.DataFrame(checks).round(3).to_string(index=False))

    status = overall_status([*drift["status"], *rates["status"], *(c["status"] for c in checks)])
    report = {"status": status, "checked_at": pd.Timestamp.now().isoformat(timespec="seconds"),
              "feature_drift": drift.to_dict(orient="records"), "rate_drift": rates.to_dict(orient="records"),
              "performance": checks}
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nOverall status: {status}. Report saved to {REPORT_FILE.relative_to(REPO_ROOT)}")

    metrics = {f"psi.{r['feature']}": r["psi"] for r in report["feature_drift"]}
    metrics.update({f"rate_change.{r['rate']}": r["change"] for r in report["rate_drift"]})
    metrics.update({f"decay_ratio.{c['check']}": c["ratio"] for c in checks})
    run_id = log_run("drift", f"drift check {pd.Timestamp.now():%Y-%m-%d %H:%M}", params=cfg, metrics=metrics,
                     artifacts=[REPORT_FILE], tags={"status": status})
    print(f"Logged to MLflow (experiment drift, run {run_id[:8]})")


if __name__ == "__main__":
    main()