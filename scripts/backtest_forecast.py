"""
Backtest the weekly revenue forecast (Phase 4.4) and forecast the next 4 weeks.

For every origin week from first_origin: forecast 1 to 4 weeks ahead with each method, using only
what was known at that week, then compare with what happened. The winner is picked on the tuning
origins only and confirmed on the later (unseen) origins.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/backtest_forecast.py
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
from src.ml.forecast import (METHODS, add_intervals, backtest, future_forecast, select_method,  # noqa: E402
                             summarize, wape, weekly_revenue)

CONFIG_FILE = REPO_ROOT / "config" / "ml.yaml"
RESULTS_FILE = REPO_ROOT / "data" / "output" / "revenue_forecast_backtest.csv"
FUTURE_FILE = REPO_ROOT / "data" / "output" / "revenue_forecast_future.csv"
CHART_FILE = REPO_ROOT / "docs" / "images" / "revenue_forecast_backtest.png"


def pct(x: float) -> str:
    return f"{x:.1%}"


def main() -> None:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))["revenue_forecast"]

    orders = read_table(cfg["source_table"])
    series = weekly_revenue(orders, cfg["first_week"], cfg["last_week"])
    bf_week = pd.Timestamp(cfg["black_friday_weeks"][-1])
    print(f"{len(series)} weeks, {series.index[0]:%Y-%m-%d} to {series.index[-1]:%Y-%m-%d}, "
          f"total R${series.sum():,.2f}")
    print(f"Black Friday week {bf_week:%Y-%m-%d}: R${series[bf_week]:,.0f} "
          f"vs R${series[:bf_week].iloc[-5:-1].mean():,.0f} average for the 4 weeks before")

    results = add_intervals(backtest(series, cfg), cfg["interval_coverage"], cfg["min_past_errors"])
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(RESULTS_FILE, index=False)

    summary = summarize(results, cfg["tuning_end"], cfg["black_friday_weeks"])
    origins = results["origin"]
    print(f"\nBacktest: {origins.nunique()} origin weeks ({origins.min():%Y-%m-%d} to {origins.max():%Y-%m-%d}), "
          f"horizons {cfg['horizons']} weeks")
    print("\nError (WAPE, lower is better), bias (+ = forecasts too high) and range coverage "
          f"(target {cfg['interval_coverage']:.0%}):")
    print(summary.map(pct).to_string())

    by_h = results.groupby(["horizon", "method"]).apply(lambda g: wape(g["actual"], g["forecast"]), include_groups=False)
    print("\nWAPE by weeks ahead:")
    print(by_h.unstack()[METHODS].map(pct).to_string())

    winner = select_method(summary)
    print(f"\nWinner (picked on tuning origins only): {winner}. "
          f"Honest error on unseen origins: {pct(summary.loc[winner, 'wape_holdout'])}")

    future = future_forecast(series, results, winner, cfg)
    future.to_csv(FUTURE_FILE, index=False)
    print(f"\nNext {len(future)} weeks ({winner}, {cfg['interval_coverage']:.0%} range):")
    for _, r in future.iterrows():
        print(f"  week of {r['target_week']:%Y-%m-%d}: R${r['forecast']:,.0f}  (R${r['low']:,.0f} to R${r['high']:,.0f})")

    # Chart: actual revenue vs the winner's 1-week-ahead forecasts and ranges
    one = results[(results["method"] == winner) & (results["horizon"] == 1)].sort_values("target_week")
    CHART_FILE.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(series.index, series.values / 1000, color="black", linewidth=1.5, label="Actual")
    ax.plot(one["target_week"], one["forecast"] / 1000, color="tab:blue", label=f"{winner}, 1 week ahead")
    ax.fill_between(one["target_week"], one["low"] / 1000, one["high"] / 1000, color="tab:blue", alpha=0.2,
                    label=f"{cfg['interval_coverage']:.0%} range")
    ax.plot(future["target_week"], future["forecast"] / 1000, color="tab:orange", marker="o", label="Next 4 weeks")
    ax.fill_between(future["target_week"], future["low"] / 1000, future["high"] / 1000, color="tab:orange", alpha=0.2)
    ax.axvline(pd.Timestamp(cfg["tuning_end"]), color="grey", linestyle="--", linewidth=1)
    ax.annotate("Black Friday", (bf_week, series[bf_week] / 1000), textcoords="offset points", xytext=(10, -5))
    ax.set(ylabel="Revenue per week (R$ thousand)", title="Weekly revenue: backtest and forecast")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(CHART_FILE, dpi=150)
    print(f"\nSaved {RESULTS_FILE.relative_to(REPO_ROOT)}, {FUTURE_FILE.relative_to(REPO_ROOT)} "
          f"and {CHART_FILE.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()