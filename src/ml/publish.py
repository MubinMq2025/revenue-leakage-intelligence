"""
Publish the Phase 4 model outputs to S3 as Parquet, so Athena and Power BI can read them (Phase 4.6).

Each table's columns and types come from config/ml_tables.yaml, the same file Terraform uses to
register the table. Before writing, a table is checked against that file: a missing column or a
value that cannot be converted stops the publish, instead of producing a table Athena cannot read.
Each publish replaces the table's previous files (the outputs are a full snapshot, not a log).
"""

from __future__ import annotations

import io

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ARROW_TYPES = {
    "string": pa.string(),
    "int": pa.int32(),
    "double": pa.float64(),
    "date": pa.date32(),
    "timestamp": pa.timestamp("ms"),
}


def to_arrow(df: pd.DataFrame, columns: dict) -> pa.Table:
    """Keep only the declared columns, in order, converted to the declared types."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    arrays = []
    for col, kind in columns.items():
        values = df[col]
        if kind == "int":
            values = pd.to_numeric(values).astype("Int32")          # whole numbers, blanks allowed
        elif kind == "double":
            values = pd.to_numeric(values).astype(float)
        elif kind == "date":
            values = pd.to_datetime(values).dt.date
        elif kind == "timestamp":
            values = pd.to_datetime(values)
        else:
            values = values.astype("string")
        arrays.append(pa.array(values, type=ARROW_TYPES[kind], from_pandas=True))
    return pa.Table.from_arrays(arrays, names=list(columns))


def table_location(glue, database: str, table: str) -> tuple[str, str]:
    """(bucket, prefix) where the Glue table expects its files."""
    location = glue.get_table(DatabaseName=database, Name=table)["Table"]["StorageDescriptor"]["Location"]
    bucket, _, prefix = location.removeprefix("s3://").partition("/")
    return bucket, prefix.rstrip("/") + "/"


def publish(df: pd.DataFrame, table: str, columns: dict, glue, s3, database: str) -> str:
    """Replace the table's files with df as one Parquet file. Returns the S3 key written."""
    data = to_arrow(df, columns)
    bucket, prefix = table_location(glue, database, table)
    old = [{"Key": o["Key"]} for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
           for o in page.get("Contents", [])]
    if old:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": old})
    buffer = io.BytesIO()
    pq.write_table(data, buffer)
    key = f"{prefix}part-00000.parquet"
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
    return key