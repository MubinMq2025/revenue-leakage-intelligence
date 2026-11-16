"""
Unit tests for the validation engine, using tiny hand-made tables so we know
exactly what the right answer is. No files, no AWS: these run in under a second.
"""

from datetime import datetime, timezone

import pandas as pd
import pytest

from src.dq_platform.outputs import build_report, output_keys
from src.dq_platform.rules import load_all_contracts, load_contract
from src.dq_platform.validator import validate

NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)


def order(**overrides) -> dict:
    """A valid order. Override any field to break it on purpose."""
    row = {
        "order_id": "o1",
        "customer_id": "c1",
        "order_status": "delivered",
        "order_purchase_timestamp": "2017-10-02 10:56:33",
        "order_approved_at": "2017-10-02 11:07:15",
        "order_delivered_carrier_date": "2017-10-04 19:55:00",
        "order_delivered_customer_date": "2017-10-10 21:25:13",
        "order_estimated_delivery_date": "2017-10-18 00:00:00",
    }
    row.update(overrides)
    return row


def item(**overrides) -> dict:
    row = {
        "order_id": "o1", "order_item_id": "1", "product_id": "p1", "seller_id": "s1",
        "shipping_limit_date": "2017-10-06 11:07:15", "price": "58.90", "freight_value": "13.29",
    }
    row.update(overrides)
    return row


@pytest.fixture(scope="module")
def orders_rules():
    return load_contract("orders")


@pytest.fixture(scope="module")
def items_rules():
    return load_contract("order_items")


def test_all_contracts_load():
    contracts = load_all_contracts()
    assert len(contracts) == 9


def test_clean_order_passes(orders_rules):
    result = validate(pd.DataFrame([order()]), orders_rules, now=NOW)
    assert len(result.valid) == 1 and len(result.rejected) == 0
    assert result.valid["dq_flags"].iloc[0] == ""


def test_missing_order_id_is_rejected(orders_rules):
    result = validate(pd.DataFrame([order(order_id="")]), orders_rules, now=NOW)
    assert len(result.rejected) == 1
    assert "OR001" in result.rejected["rejection_reasons"].iloc[0]


def test_duplicate_order_keeps_first(orders_rules):
    result = validate(pd.DataFrame([order(), order()]), orders_rules, now=NOW)
    assert len(result.valid) == 1
    assert result.rejected["rejection_reasons"].iloc[0] == "OR002"


def test_bad_timestamp_is_rejected(orders_rules):
    result = validate(pd.DataFrame([order(order_approved_at="02/10/2017")]), orders_rules, now=NOW)
    assert result.rejected["rejection_reasons"].iloc[0] == "OR004"


def test_delivered_without_date_is_kept_and_flagged(orders_rules):
    result = validate(pd.DataFrame([order(order_delivered_customer_date="")]), orders_rules, now=NOW)
    assert len(result.valid) == 1 and len(result.rejected) == 0
    assert result.valid["dq_flags"].iloc[0] == "OR006"
    assert result.flagged_rows == 1


def test_shipped_without_date_is_fine(orders_rules):
    result = validate(pd.DataFrame([order(order_status="shipped", order_delivered_customer_date="")]), orders_rules, now=NOW)
    assert result.valid["dq_flags"].iloc[0] == ""


def test_composite_key_allows_two_items_per_order(items_rules):
    df = pd.DataFrame([item(order_item_id="1"), item(order_item_id="2"), item(order_item_id="2")])
    result = validate(df, items_rules, now=NOW)
    assert len(result.valid) == 2
    assert result.rejected["rejection_reasons"].iloc[0] == "OI002"


def test_shipping_date_in_2020_is_flagged(items_rules):
    result = validate(pd.DataFrame([item(shipping_limit_date="2020-04-09 22:35:08")]), items_rules, now=NOW)
    assert result.valid["dq_flags"].iloc[0] == "OI007"


def test_zero_price_is_rejected_zero_freight_is_not(items_rules):
    result = validate(pd.DataFrame([item(price="0"), item(order_item_id="2", freight_value="0")]), items_rules, now=NOW)
    assert result.rejected["rejection_reasons"].tolist() == ["OI004"]
    assert len(result.valid) == 1


def test_output_keys_follow_table_layout():
    keys = output_keys("raw/orders/load_date=2026-11-16/olist_orders_dataset.csv")
    assert keys["validated"] == "validated/orders/load_date=2026-11-16/olist_orders_dataset.csv"
    assert keys["rejected"] == "quarantine/orders/load_date=2026-11-16/olist_orders_dataset_rejected.csv"
    assert keys["dq_report"] == "dq-reports/orders/load_date=2026-11-16/olist_orders_dataset_dq_report.json"


def test_report_status_reflects_warnings(orders_rules):
    key = "raw/orders/load_date=2026-11-16/olist_orders_dataset.csv"
    result = validate(pd.DataFrame([order(order_delivered_customer_date="")]), orders_rules, now=NOW)
    report = build_report(result, orders_rules, key)
    assert report["status"] == "PASSED_WITH_WARNINGS"
    assert report["flagged_rows"] == 1
    assert {w["rule_id"] for w in report["warnings"]} >= {"OR006", "OR100"}