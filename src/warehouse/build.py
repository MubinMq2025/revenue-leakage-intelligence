"""
Build every model stored in sql/models/ ("models as code").

Layers are built in order, and each layer only reads from the ones before it:
    dims, facts, recon  -> VIEWS  (file = CREATE OR REPLACE VIEW ...; cheap, always in sync)
    marts               -> TABLES (file = a SELECT; materialized as Parquet so dashboards
                                   read one small table instead of re-running every join)
Inside a layer, a model that mentions another model of the same layer is built after it.

Used by scripts/create_models.py (laptop) and lambda/models_handler.py (Step Functions).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.athena_tools import DATABASE, run_query

REPO_ROOT = Path(__file__).resolve().parents[2]  # repo root locally, /var/task in Lambda
MODELS_DIR = REPO_ROOT / "sql" / "models"
LAYERS = [("dims", "view"), ("facts", "view"), ("recon", "view"), ("marts", "table")]  # build order
LAYER_NAMES = [name for name, _ in LAYERS]


def dependency_order(files: list[Path]) -> list[Path]:
    """Sort one layer's files so a model comes after any same-layer model it mentions."""
    by_name = {f.stem: f for f in files}
    deps = {
        name: {other for other in by_name if other != name
               and re.search(rf"\b{re.escape(other)}\b", f.read_text(encoding="utf-8"))}
        for name, f in by_name.items()
    }
    ordered: list[str] = []
    while deps:
        ready = sorted(name for name, needs in deps.items() if needs <= set(ordered))
        if not ready:
            raise ValueError(f"Circular dependency between models: {sorted(deps)}")
        ordered.append(ready[0])
        del deps[ready[0]]
    return [by_name[name] for name in ordered]


def model_files(models_dir: Path = MODELS_DIR) -> list[tuple[Path, str]]:
    """All model files in build order, each with its kind ('view' or 'table')."""
    return [
        (f, kind)
        for layer, kind in LAYERS
        for f in dependency_order(sorted((models_dir / layer).glob("*.sql")))
    ]


def materialize(athena, glue, s3, name: str, select_sql: str) -> None:
    """Rebuild a mart as a Parquet table: remove the old one (and its files), then CTAS."""
    try:
        table = glue.get_table(DatabaseName=DATABASE, Name=name)["Table"]
    except glue.exceptions.EntityNotFoundException:
        table = None

    if table and table.get("TableType") == "VIRTUAL_VIEW":
        run_query(athena, f"DROP VIEW IF EXISTS {DATABASE}.{name}")
    elif table:
        # Dropping an external table keeps its files, so delete them first
        location = table["StorageDescriptor"]["Location"]  # s3://bucket/prefix/
        bucket, _, prefix = location.removeprefix("s3://").partition("/")
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
        run_query(athena, f"DROP TABLE IF EXISTS {DATABASE}.{name}")

    # The workgroup decides where the files go (athena-results/tables/<query-id>/)
    run_query(
        athena,
        f"CREATE TABLE {DATABASE}.{name} WITH (format = 'PARQUET', write_compression = 'SNAPPY') AS\n"
        + select_sql.strip().rstrip(";"),
    )


def build_all(athena, glue, s3, models_dir: Path = MODELS_DIR) -> list[dict]:
    """Build every model in order. Returns one result per model; never stops half way.

    A failed model is recorded (not raised), so one bad file does not hide problems in the
    others. The caller decides what a failure means (exit code locally, exception in Lambda).
    """
    results = []
    for sql_file, kind in model_files(models_dir):
        sql = sql_file.read_text(encoding="utf-8")
        result = {"model": f"{sql_file.parent.name}/{sql_file.stem}", "kind": kind, "status": "OK"}
        try:
            if kind == "view":
                run_query(athena, sql)
            else:
                materialize(athena, glue, s3, sql_file.stem, sql)
        except RuntimeError as err:
            result.update(status="FAILED", error=str(err))
        results.append(result)
    return results
