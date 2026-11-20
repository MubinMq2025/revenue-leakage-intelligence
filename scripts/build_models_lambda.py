"""
Build the "models" Lambda package: build/models_lambda.zip  (Phase 5)

What goes in the zip:
    models_handler.py            (from lambda/)
    src/athena_tools.py          (run SQL in Athena)
    src/warehouse/*.py           (build models, run checks, leakage check)
    sql/models/<layer>/*.sql     (every model)
    config/model_checks.yaml     (the checks)
    config/alerts.yaml           (the alert lines)
    yaml/                        (PyYAML, Linux build, since Lambda runs on Linux)

boto3 is already in the Lambda Python runtime, so no layer is needed.

Usage (from the repo root, with .venv active):
    python scripts/build_models_lambda.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = REPO_ROOT / "build" / "models_lambda_package"
ZIP_PATH = REPO_ROOT / "build" / "models_lambda.zip"

FILES = [
    ("lambda/models_handler.py", "models_handler.py"),
    ("src/athena_tools.py", "src/athena_tools.py"),
    ("config/model_checks.yaml", "config/model_checks.yaml"),
    ("config/alerts.yaml", "config/alerts.yaml"),
]


def main() -> None:
    # 1. Start from a clean folder so old files never sneak into the package
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    # 2. Copy our code, the models and the config
    for source, target in FILES:
        (BUILD_DIR / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / source, BUILD_DIR / target)
    (BUILD_DIR / "src" / "__init__.py").touch()
    shutil.copytree(REPO_ROOT / "src" / "warehouse", BUILD_DIR / "src" / "warehouse",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "sql" / "models", BUILD_DIR / "sql" / "models")
    models = len(list((BUILD_DIR / "sql" / "models").rglob("*.sql")))

    # 3. Install PyYAML built for Lambda's Linux environment (not for Windows)
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "pyyaml",
            "--target", str(BUILD_DIR),
            "--platform", "manylinux2014_x86_64",
            "--implementation", "cp",
            "--python-version", "3.12",
            "--only-binary=:all:",
            "--quiet",
        ],
        check=True,
    )

    # 4. Zip it with forward-slash paths (Lambda runs on Linux)
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(BUILD_DIR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(BUILD_DIR).as_posix())

    size_kb = ZIP_PATH.stat().st_size / 1024
    print(f"Built {ZIP_PATH.relative_to(REPO_ROOT)} ({size_kb:.0f} KB) with {models} models")


if __name__ == "__main__":
    main()
