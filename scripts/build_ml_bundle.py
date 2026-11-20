"""
Build the code bundle for the ML Glue job: build/ml_bundle.zip

What goes in the zip (everything the pipeline needs, nothing else):
    src/        the shared code (Athena helpers and src/ml)
    scripts/    the pipeline steps and scripts/run_ml_pipeline.py
    config/     ml.yaml, ml_tables.yaml and the other settings

Data, outputs, tests and caches are left out. Terraform uploads the zip to S3, and the Glue job
(glue/run_ml.py) downloads and unzips it before running the pipeline.

Usage (from the repo root, with .venv active), before terraform plan:
    python scripts/build_ml_bundle.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = REPO_ROOT / "build" / "ml_bundle.zip"
FOLDERS = ["src", "scripts", "config"]
SKIP = {"__pycache__", ".pytest_cache"}


def bundle_files(root: Path = REPO_ROOT) -> list[Path]:
    files = []
    for folder in FOLDERS:
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and not SKIP & set(path.parts) and path.suffix != ".pyc":
                files.append(path)
    return files


def build(zip_path: Path) -> int:
    """Write the zip and return how many files went in."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    files = bundle_files()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            # fixed timestamp, so the zip only changes when the code changes (Terraform re-uploads on change)
            info = zipfile.ZipInfo(path.relative_to(REPO_ROOT).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    return len(files)


def main() -> None:
    count = build(ZIP_PATH)
    print(f"Built {ZIP_PATH.relative_to(REPO_ROOT)}: {count} files, {ZIP_PATH.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()