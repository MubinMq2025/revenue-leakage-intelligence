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