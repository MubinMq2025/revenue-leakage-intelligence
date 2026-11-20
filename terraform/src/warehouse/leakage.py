"""
The daily leakage check: is the latest month's money at risk above the line in config/alerts.yaml?

It also reads the overall status of the latest ML drift check (ml_drift_checks), so the alert email
says both "how much money is at risk" and "can we still trust the models".

Returns a small JSON-friendly dict. Step Functions reads its "alert" field to decide whether to email.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.athena_tools import DATABASE, fetch_rows, run_query

REPO_ROOT = Path(__file__).resolve().parents[2]
ALERTS_FILE = REPO_ROOT / "config" / "alerts.yaml"


def load_alert_config(path: Path = ALERTS_FILE) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def latest_month_sql(table: str, min_orders: int, database: str = DATABASE) -> str:
    """The most recent purchase month with at least min_orders orders, with its money at risk."""
    return f"""
SELECT
    CAST(date_trunc('month', purchase_date_key) AS date)  AS month,
    COUNT(*)                                              AS orders,
    SUM(CAST(paid_amount AS double))                      AS paid_rs,
    SUM(CAST(amount_at_risk AS double))                   AS at_risk_rs
FROM {database}.{table}
WHERE purchase_date_key IS NOT NULL
GROUP BY 1
HAVING COUNT(*) >= {int(min_orders)}
ORDER BY 1 DESC
LIMIT 1
""".strip()


def drift_sql(table: str, database: str = DATABASE) -> str:
    return f"SELECT MAX(overall_status) AS overall_status, MAX(checked_at) AS checked_at FROM {database}.{table}"


def decide(month: dict, max_rate: float, drift_status: str, alert_on_drift: bool) -> dict:
    """Pure decision logic (no AWS), so it is easy to unit test."""
    paid, at_risk = float(month["paid_rs"] or 0), float(month["at_risk_rs"] or 0)
    rate = at_risk / paid if paid else 0.0
    leakage_breach = rate > max_rate
    drift_breach = alert_on_drift and drift_status == "ALERT"
    reasons = []
    if leakage_breach:
        reasons.append(f"at-risk rate {rate:.2%} is above the {max_rate:.2%} line")
    if drift_breach:
        reasons.append("model drift is ALERT")
    return {
        "month": month["month"],
        "orders": int(month["orders"]),
        "paid_rs": round(paid, 2),
        "at_risk_rs": round(at_risk, 2),
        "at_risk_rate": round(rate, 6),
        "max_at_risk_rate": max_rate,
        "drift_status": drift_status,
        "alert": leakage_breach or drift_breach,
        "reasons": reasons,
    }


def summary_text(result: dict) -> str:
    """Plain-English email body."""
    head = "ALERT: " + "; ".join(result["reasons"]) if result["alert"] else "All clear"
    return (
        f"{head}\n\n"
        f"Month checked:   {result['month']} ({result['orders']:,} orders)\n"
        f"Paid:            R${result['paid_rs']:,.2f}\n"
        f"Money at risk:   R${result['at_risk_rs']:,.2f} ({result['at_risk_rate']:.2%})\n"
        f"Alert line:      {result['max_at_risk_rate']:.2%}\n"
        f"Model drift:     {result['drift_status']}\n"
    )


def check_leakage(athena, max_rate: float | None = None, config: dict | None = None) -> dict:
    """Run the check. max_rate overrides the config line (used to test the alert path)."""
    cfg = config or load_alert_config()
    leak, drift = cfg["leakage"], cfg["drift"]
    line = float(leak["max_at_risk_rate"] if max_rate is None else max_rate)

    rows = fetch_rows(athena, run_query(athena, latest_month_sql(leak["source_table"], leak["min_orders"])))
    if not rows:
        raise RuntimeError(f"No month has at least {leak['min_orders']} orders in {leak['source_table']}")

    drift_rows = fetch_rows(athena, run_query(athena, drift_sql(drift["table"])))
    drift_status = (drift_rows[0].get("overall_status") if drift_rows else None) or "UNKNOWN"

    result = decide(rows[0], line, drift_status, bool(drift.get("alert_on_drift", False)))
    result["summary"] = summary_text(result)
    return result
