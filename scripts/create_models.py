"""
Create (or update) every star schema view stored in sql/models/.

Models are kept as .sql files in Git ("models as code"), so they are reviewed,
versioned and can be rebuilt in any environment with one command.
Dimensions are created before facts, because facts are built to join to them.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/create_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # lets this script import from src/

from src.athena_tools import DATABASE, WORKGROUP, athena_client, run_query  # noqa: E402

MODELS_DIR = REPO_ROOT / "sql" / "models"
LAYERS = ["dims", "facts", "recon", "marts"]  # build order: each layer reads from the ones before it

def model_files(models_dir: Path = MODELS_DIR) -> list[Path]:
    """All model files in build order: every dimension first, then every fact."""
    return [f for layer in LAYERS for f in sorted((models_dir / layer).glob("*.sql"))]


def main() -> None:
    athena = athena_client()
    failures = 0

    for sql_file in model_files():
        name = f"{sql_file.parent.name}/{sql_file.stem}"
        try:
            run_query(athena, sql_file.read_text(encoding="utf-8"))
            print(f"OK      {name}")
        except RuntimeError as err:
            failures += 1
            print(f"FAILED  {name}: {err}")

    if failures:
        sys.exit(f"{failures} model(s) failed")
    print(f"All models created in {DATABASE} (workgroup {WORKGROUP})")


if __name__ == "__main__":
    main()
