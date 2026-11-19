"""
Small helpers for running SQL in Athena from Python scripts and tests.

Defaults match what Terraform creates (terraform/athena.tf, glue_catalog.tf).
Credentials come from the normal AWS chain (your AWS_PROFILE=dq setting locally).
"""

from __future__ import annotations

import os
import time

import boto3

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
WORKGROUP = os.environ.get("RLI_WORKGROUP", "rli-dev")
DATABASE = os.environ.get("RLI_DATABASE", "rli_dev_olist")


def athena_client():
    return boto3.Session(region_name=REGION).client("athena")


def run_query(athena, sql: str, database: str = DATABASE, workgroup: str = WORKGROUP, poll_seconds: float = 1.0) -> str:
    """Run one SQL statement, wait for it to finish, and return its execution ID.

    Raises RuntimeError with Athena's reason if the query fails or is cancelled.
    """
    execution_id = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        WorkGroup=workgroup,
    )["QueryExecutionId"]

    while True:
        status = athena.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]["Status"]
        state = status["State"]
        if state == "SUCCEEDED":
            return execution_id
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"{state}: {status.get('StateChangeReason', 'no reason given')}")
        time.sleep(poll_seconds)


def fetch_rows(athena, execution_id: str) -> list[dict]:
    """Return a finished query's results as a list of {column: value} dicts (values are text)."""
    rows, header = [], None
    for page in athena.get_paginator("get_query_results").paginate(QueryExecutionId=execution_id):
        for row in page["ResultSet"]["Rows"]:
            values = [cell.get("VarCharValue") for cell in row["Data"]]
            if header is None:
                header = values  # the first row of the first page holds the column names
                continue
            rows.append(dict(zip(header, values)))
    return rows



def read_table(name: str, database: str = DATABASE):
    """Read a materialized (Parquet) table straight from S3 into a pandas DataFrame.

    Much faster than paging query results through the Athena API. Works for marts (tables), not views.
    """
    import io

    import pandas as pd
    import pyarrow.parquet as pq

    session = boto3.Session(region_name=REGION)
    table = session.client("glue").get_table(DatabaseName=database, Name=name)["Table"]
    if table.get("TableType") == "VIRTUAL_VIEW":
        raise ValueError(f"{name} is a view; read_table only reads materialized tables")

    bucket, _, prefix = table["StorageDescriptor"]["Location"].removeprefix("s3://").partition("/")
    s3 = session.client("s3")
    frames = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
        for obj in page.get("Contents", []):
            if obj["Size"] == 0:
                continue
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            frames.append(pq.read_table(io.BytesIO(body)).to_pandas(date_as_object=False))
    if not frames:
        raise ValueError(f"{name} has no data files at s3://{bucket}/{prefix}")
    return pd.concat(frames, ignore_index=True)