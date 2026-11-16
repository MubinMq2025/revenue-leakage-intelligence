"""
Tests for the Lambda handler, using a fake S3 client (no AWS needed).

The folder is named "lambda", which is a Python keyword, so we import it with importlib.
"""

import importlib
import io
import json

import pytest

handler = importlib.import_module("lambda.handler")

RAW_KEY = "raw/orders/load_date=2026-11-16/olist_orders_dataset.csv"
CSV = (
    "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,"
    "order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date\n"
    "o1,c1,delivered,2017-10-02 10:56:33,2017-10-02 11:07:15,2017-10-04 19:55:00,2017-10-10 21:25:13,2017-10-18 00:00:00\n"
    "o2,c2,delivered,2017-10-03 10:00:00,2017-10-03 11:00:00,2017-10-05 10:00:00,,2017-10-20 00:00:00\n"
    ",c3,shipped,2017-10-04 10:00:00,,,,2017-10-21 00:00:00\n"
)


class FakeS3:
    """Records uploads in memory instead of talking to AWS."""

    def __init__(self):
        self.uploaded = {}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(CSV.encode())}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.uploaded[Key] = Body.decode()


@pytest.fixture
def fake_s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(handler, "s3", fake)
    monkeypatch.setenv("DATA_BUCKET", "test-bucket")
    return fake


def test_manual_event_writes_three_outputs(fake_s3):
    result = handler.lambda_handler({"key": RAW_KEY}, None)
    processed = result["processed"][0]

    assert processed["dataset"] == "orders"
    assert processed["rejected_rows"] == 1   # o3 has no order_id
    assert processed["flagged_rows"] == 1    # o2 delivered with no delivery date
    assert set(fake_s3.uploaded) == {
        "validated/orders/load_date=2026-11-16/olist_orders_dataset.csv",
        "quarantine/orders/load_date=2026-11-16/olist_orders_dataset_rejected.csv",
        "dq-reports/orders/load_date=2026-11-16/olist_orders_dataset_dq_report.json",
    }
    report = json.loads(fake_s3.uploaded["dq-reports/orders/load_date=2026-11-16/olist_orders_dataset_dq_report.json"])
    assert report["status"] == "PASSED_WITH_WARNINGS"


def test_eventbridge_event_is_understood(fake_s3):
    event = {"detail": {"bucket": {"name": "test-bucket"}, "object": {"key": RAW_KEY}}}
    assert len(handler.lambda_handler(event, None)["processed"]) == 1


def test_non_raw_objects_are_skipped(fake_s3):
    result = handler.lambda_handler({"key": "validated/orders/load_date=2026-11-16/x.csv"}, None)
    assert result["processed"] == [] and len(result["skipped"]) == 1