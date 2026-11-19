"""
Tests for publishing model outputs (src/ml/publish.py), with a fake S3 and Glue.
"""

import io

import pandas as pd
import pyarrow.parquet as pq
import pytest
import yaml

from src.ml.publish import publish, to_arrow

COLUMNS = {"seller_id": "string", "queue_rank": "int", "chance": "double", "snapshot": "date",
           "purchased_at": "timestamp"}


def frame():
    return pd.DataFrame({"seller_id": ["a", "b"], "queue_rank": [1, None], "chance": [0.1, 0.2],
                         "snapshot": ["2018-06-01", "2018-06-01"],
                         "purchased_at": ["2018-04-01 10:00:00", "2018-04-02 11:30:00"], "extra": [1, 2]})


def test_columns_are_kept_in_order_with_the_declared_types():
    table = to_arrow(frame(), COLUMNS)
    assert table.column_names == list(COLUMNS)                    # "extra" is dropped
    assert [str(t) for t in table.schema.types] == ["string", "int32", "double", "date32[day]", "timestamp[ms]"]
    assert table.column("queue_rank").to_pylist() == [1, None]     # blanks stay blank


def test_a_missing_column_stops_the_publish():
    with pytest.raises(ValueError, match="missing columns"):
        to_arrow(frame().drop(columns="chance"), COLUMNS)


def test_every_ml_table_uses_a_known_type():
    from src.ml.publish import ARROW_TYPES

    tables = yaml.safe_load(open("config/ml_tables.yaml", encoding="utf-8"))["tables"]
    assert len(tables) == 5
    for spec in tables.values():
        assert set(spec["columns"].values()) <= set(ARROW_TYPES)


class FakeGlue:
    def get_table(self, DatabaseName, Name):
        return {"Table": {"StorageDescriptor": {"Location": f"s3://bucket/ml/{Name}/"}}}


class FakeS3:
    def __init__(self):
        self.objects = {"ml/t/old-file.parquet": b"old"}

    def get_paginator(self, _):
        objects = self.objects

        class Pages:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": k} for k in objects if k.startswith(Prefix)]}]
        return Pages()

    def delete_objects(self, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"])

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


def test_publish_replaces_old_files_with_one_readable_parquet_file():
    s3 = FakeS3()
    key = publish(frame(), "t", COLUMNS, FakeGlue(), s3, database="db")
    assert list(s3.objects) == [key] == ["ml/t/part-00000.parquet"]
    back = pq.read_table(io.BytesIO(s3.objects[key])).to_pandas()
    assert back["seller_id"].tolist() == ["a", "b"] and back["queue_rank"].isna().tolist() == [False, True]