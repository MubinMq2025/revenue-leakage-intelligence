"""
AWS Glue ETL job: validated/<table>/ (CSV) -> curated/<table>/ (Parquet), for all 9 Olist tables.

The job is driven by the same data contracts the Lambda uses (config/contracts/*.yaml).
Terraform converts them to one JSON file in S3 (glue-config/contracts.json), so there is
a single source of truth for column names and types.

For each table:
Extract   Read only the LATEST load_date. Every Olist load is a full snapshot,
          so the newest load replaces the older ones (no double counting).
Transform 1. Cast text columns to the types declared in the contract.
          2. Rename columns that declare rename_to (e.g. the misspelled "lenght").
          3. Drop exact duplicate rows (geolocation has ~26% of them).
          4. Turn empty dq_flags into NULL and add lineage columns (load_date, curated_at).
Load      Overwrite curated/<table>/ as Parquet.

Re-running the job rebuilds curated/ from validated/, so the same input always gives
the same output (idempotent).

Glue passes arguments like:  --DATA_BUCKET rli-dev-046749917047
"""

from __future__ import annotations

import json
import sys

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

# Contract type -> Spark SQL type
SPARK_TYPES = {
    "string": "string",
    "integer": "int",
    "decimal": "decimal(12,2)",
    "double": "double",
    "timestamp": "timestamp",
}


def read_latest_snapshot(spark: SparkSession, path: str) -> tuple[DataFrame, str]:
    """Read validated CSVs for one table and keep only the newest load_date folder."""
    df = (
        spark.read.option("header", "true")
        .option("escape", '"')           # pandas writes quotes inside values as ""
        .option("multiLine", "true")     # review comments contain line breaks inside quotes
        .option("inferSchema", "false")  # keep everything as text; we cast explicitly below
        .csv(path)
    )
    latest = df.agg(F.max("load_date")).first()[0]
    return df.filter(F.col("load_date") == latest), latest


def curate(df: DataFrame, contract: dict) -> DataFrame:
    """Cast, rename and de-duplicate one table according to its contract."""
    out = df
    for name, spec in contract["columns"].items():
        out = out.withColumn(name, F.col(name).cast(SPARK_TYPES[spec["type"]]))

    out = out.dropDuplicates()  # exact duplicate rows only; key duplicates were rejected by the Lambda

    for name, spec in contract["columns"].items():
        if spec.get("rename_to"):
            out = out.withColumnRenamed(name, spec["rename_to"])

    final_names = [spec.get("rename_to") or name for name, spec in contract["columns"].items()]
    return (
        out.withColumn("dq_flags", F.when(F.col("dq_flags") == "", None).otherwise(F.col("dq_flags")))
        .withColumn("curated_at", F.current_timestamp())
        .select(*final_names, "dq_flags", "load_date", "curated_at")
    )


def main() -> None:
    import boto3
    from awsglue.utils import getResolvedOptions  # only available inside AWS Glue

    args = getResolvedOptions(sys.argv, ["JOB_NAME", "DATA_BUCKET"])
    bucket = args["DATA_BUCKET"]

    body = boto3.client("s3").get_object(Bucket=bucket, Key="glue-config/contracts.json")["Body"].read()
    contracts = json.loads(body)

    spark = (
        SparkSession.builder.appName(args["JOB_NAME"])
        # Keep load_date as text like "2026-11-16" (not converted to a date)
        .config("spark.sql.sources.partitionColumnTypeInference.enabled", "false")
        # Treat source timestamps as UTC so values are stored exactly as received
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )

    for table, contract in sorted(contracts.items()):
        raw, load_date = read_latest_snapshot(spark, f"s3://{bucket}/validated/{table}/")
        curated = curate(raw, contract)
        curated.write.mode("overwrite").parquet(f"s3://{bucket}/curated/{table}/")

        input_rows, output_rows = raw.count(), curated.count()
        print(f"{table}: load_date={load_date} | input {input_rows} | curated {output_rows} | duplicates removed {input_rows - output_rows}")

    print("All tables curated")


if __name__ == "__main__":
    main()