"""
Weekly revenue forecast and its backtest (Phase 4.4).

Stand at a week (the "origin"), forecast the next 1 to 4 weeks, then compare with what happened.
Three methods:

    naive     next weeks = this week
    avg_4w    next weeks = average of the last 4 weeks
    lightgbm  learns how revenue moves relative to its recent level (lags, trend, Black Friday)

Tree models cannot predict values bigger than anything they have seen, and Olist grew fast, so
LightGBM predicts a RATIO (target week / last-4-week average) and we multiply it back. Every
model is trained only on weeks whose outcome was known at the origin.

Ranges (low to high) come from each method's own past errors: if past forecasts were between
15% too low and 12% too high 80% of the time, the next range is forecast x [0.85, 1.12].
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

METHODS = ["naive", "avg_4w", "lightgbm"]
FEATURES = ["lag_ratio_0", "lag_ratio_1", "lag_ratio_2", "lag_ratio_3", "trend_4_8", "horizon",
            "target_month", "target_is_black_friday", "target_after_black_friday"]


def weekly_revenue(orders: pd.DataFrame, first_week, last_week) -> pd.Series:
    """Paid R$ per week (weeks start Monday), with empty weeks as 0."""
    dates = pd.to_datetime(orders["purchase_date_key"])
    week = dates - pd.to_timedelta(dates.dt.weekday, unit="D")
    series = orders["paid_amount"].astype(float).groupby(week).sum()
    return series.reindex(pd.date_range(first_week, last_week, freq="W-MON"), fill_value=0.0)


def features_at(series: pd.Series, origin_pos: int, horizon: int, black_friday: set) -> dict:
    """What we know at the origin week, described relative to the last-4-week average."""
    past = series.iloc[: origin_pos + 1]
    level = past.iloc[-4:].mean()
    target_week = series.index[0] + timedelta(weeks=origin_pos + horizon)
    row = {f"lag_ratio_{i}": past.iloc[-1 - i] / level for i in range(4)}
    row["trend_4_8"] = level / past.iloc[-8:].mean()
    row["horizon"] = horizon
    row["target_month"] = target_week.month
    row["target_is_black_friday"] = int(target_week in black_friday)
    row["target_after_black_friday"] = int(target_week - timedelta(weeks=1) in black_friday)
    row["level"] = level
    return row


def lightgbm_forecasts(series: pd.Series, origin_pos: int, cfg: dict, black_friday: set) -> dict:
    """One model for all horizons, trained on earlier origins whose target week is already known.

    Returns {horizon: forecast in R$}.
    """
    import lightgbm as lgb

    rows, targets = [], []
    for h in cfg["horizons"]:
        for pos in range(8, origin_pos - h + 1):            # target week pos + h is on or before the origin
            f = features_at(series, pos, h, black_friday)
            rows.append(f)
            targets.append(series.iloc[pos + h] / f["level"])
    model = lgb.LGBMRegressor(**cfg["lightgbm"]["params"], random_state=cfg["random_state"])
    model.fit(pd.DataFrame(rows)[FEATURES], targets)

    out = {}
    for h in cfg["horizons"]:
        now = features_at(series, origin_pos, h, black_friday)
        out[h] = float(model.predict(pd.DataFrame([now])[FEATURES])[0] * now["level"])
    return out


def backtest(series: pd.Series, cfg: dict) -> pd.DataFrame:
    """One row per (origin, horizon, method) with the forecast and the actual value."""
    black_friday = {pd.Timestamp(w) for w in cfg["black_friday_weeks"]}
    first = series.index.get_loc(pd.Timestamp(cfg["first_origin"]))
    rows = []
    for origin_pos in range(first, len(series) - 1):
        past = series.iloc[: origin_pos + 1]
        ml = lightgbm_forecasts(series, origin_pos, cfg, black_friday)
        for h in cfg["horizons"]:
            if origin_pos + h >= len(series):
                continue
            forecasts = {"naive": past.iloc[-1], "avg_4w": past.iloc[-4:].mean(), "lightgbm": ml[h]}
            for method, value in forecasts.items():
                rows.append({"origin": series.index[origin_pos], "horizon": h,
                             "target_week": series.index[origin_pos + h], "method": method,
                             "forecast": float(value), "actual": float(series.iloc[origin_pos + h])})
    return pd.DataFrame(rows)


def add_intervals(results: pd.DataFrame, coverage: float, min_past_errors: int) -> pd.DataFrame:
    """Low/high range from the same method's past errors at the same horizon.

    Only errors whose actual value was known at the origin (target week <= origin) are used.
    """
    results = results.sort_values("origin").copy()
    results["ratio"] = results["actual"] / results["forecast"]
    tail = (1 - coverage) / 2
    lo, hi = [], []
    for _, row in results.iterrows():
        past = results[(results["method"] == row["method"]) & (results["horizon"] == row["horizon"])
                       & (results["target_week"] <= row["origin"])]["ratio"]
        if len(past) < min_past_errors:
            lo.append(np.nan)
            hi.append(np.nan)
        else:
            lo.append(row["forecast"] * past.quantile(tail))
            hi.append(row["forecast"] * past.quantile(1 - tail))
    results["low"], results["high"] = lo, hi
    return results.drop(columns="ratio")


def wape(actual, forecast) -> float:
    """Total absolute error as a share of total actual revenue."""
    actual, forecast = np.asarray(actual, float), np.asarray(forecast, float)
    return float(np.abs(actual - forecast).sum() / actual.sum())


def summarize(results: pd.DataFrame, tuning_end, black_friday_weeks) -> pd.DataFrame:
    """WAPE on tuning and holdout origins, WAPE without Black Friday weeks, bias and range coverage."""
    bf = {pd.Timestamp(w) for w in black_friday_weeks}
    out = []
    for method, g in results.groupby("method"):
        tuning, holdout = g[g["origin"] < pd.Timestamp(tuning_end)], g[g["origin"] >= pd.Timestamp(tuning_end)]
        normal = g[~g["target_week"].isin(bf)]
        ranged = g.dropna(subset=["low", "high"])
        out.append({
            "method": method,
            "wape_tuning": wape(tuning["actual"], tuning["forecast"]),
            "wape_holdout": wape(holdout["actual"], holdout["forecast"]),
            "wape_no_black_friday": wape(normal["actual"], normal["forecast"]),
            "bias": float((g["forecast"].sum() - g["actual"].sum()) / g["actual"].sum()),
            "range_coverage": float(((ranged["actual"] >= ranged["low"]) & (ranged["actual"] <= ranged["high"])).mean()),
        })
    return pd.DataFrame(out).set_index("method").loc[METHODS]


def select_method(summary: pd.DataFrame) -> str:
    """The method with the lowest WAPE on the tuning origins (holdout origins play no part)."""
    return str(summary["wape_tuning"].idxmin())


def future_forecast(series: pd.Series, results: pd.DataFrame, method: str, cfg: dict) -> pd.DataFrame:
    """Forecast the weeks after the last known week, with ranges from all past errors of that method."""
    black_friday = {pd.Timestamp(w) for w in cfg["black_friday_weeks"]}
    last = len(series) - 1
    if method == "lightgbm":
        values = lightgbm_forecasts(series, last, cfg, black_friday)
    else:
        value = series.iloc[-1] if method == "naive" else series.iloc[-4:].mean()
        values = {h: float(value) for h in cfg["horizons"]}

    tail = (1 - cfg["interval_coverage"]) / 2
    rows = []
    for h, value in values.items():
        past = results[(results["method"] == method) & (results["horizon"] == h)]
        ratio = past["actual"] / past["forecast"]
        rows.append({"origin": series.index[-1], "horizon": h,
                     "target_week": series.index[-1] + timedelta(weeks=h), "method": method,
                     "forecast": value, "low": value * ratio.quantile(tail), "high": value * ratio.quantile(1 - tail)})
    return pd.DataFrame(rows)