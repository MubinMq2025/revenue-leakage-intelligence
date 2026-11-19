"""
Experiment tracking with MLflow (Phase 4.5).

Every backtest run is recorded: the settings it used (params), the scores it got (metrics),
its charts and CSVs (artifacts), and the Git commit of the code. So any number in the README
can be traced back to the exact run, code and settings that produced it.

Runs are stored locally in data/mlflow/ (not in Git). To browse them:
    mlflow ui --backend-store-uri sqlite:///data/mlflow/mlflow.db
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MLFLOW_DIR = REPO_ROOT / "data" / "mlflow"


def flatten(params: dict, prefix: str = "") -> dict:
    """{"lightgbm": {"params": {"num_leaves": 7}}} -> {"lightgbm.params.num_leaves": "7"}."""
    flat = {}
    for key, value in params.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{name}."))
        else:
            flat[name] = str(value)
    return flat


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def log_run(experiment: str, run_name: str, params: dict, metrics: dict,
            artifacts=(), tags: dict | None = None, mlflow_dir: Path = MLFLOW_DIR) -> str:
    """Record one run and return its MLflow run ID."""
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")   # keep MLflow's start-up tips out of our output
    import mlflow

    mlflow_dir.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri("sqlite:///" + (mlflow_dir / "mlflow.db").as_posix())
    if mlflow.get_experiment_by_name(experiment) is None:
        mlflow.create_experiment(experiment, artifact_location=(mlflow_dir / "artifacts").as_uri())
    mlflow.set_experiment(experiment)

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params(flatten(params))
        mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
        mlflow.set_tags({"git_commit": git_commit(), **(tags or {})})
        for path in artifacts:
            mlflow.log_artifact(str(path))
    return run.info.run_id
