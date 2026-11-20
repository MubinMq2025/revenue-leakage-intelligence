"""
Create (or refresh) every model stored in sql/models/.

The logic lives in src/warehouse/build.py, shared with the "models" Lambda that
Step Functions runs every day. This script is the laptop entry point.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/create_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import DATABASE, REGION, WORKGROUP, athena_client  # noqa: E402
from src.warehouse.build import (  # noqa: E402,F401  (re-exported for tests)
    LAYER_NAMES, LAYERS, MODELS_DIR, build_all, dependency_order, materialize, model_files,
)


def main() -> None:
    session = boto3.Session(region_name=REGION)
    results = build_all(athena_client(), session.client("glue"), session.client("s3"))

    for r in results:
        line = f"{r['status']:<8}{r['model']} ({r['kind']})"
        print(line + (f": {r['error']}" if "error" in r else ""))

    failures = sum(r["status"] != "OK" for r in results)
    if failures:
        sys.exit(f"{failures} model(s) failed")
    print(f"All models created in {DATABASE} (workgroup {WORKGROUP})")


if __name__ == "__main__":
    main()
