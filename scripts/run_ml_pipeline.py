"""
Run the whole Phase 4 machine learning pipeline, in order, with one command.

The same file runs on your laptop and inside the scheduled AWS Glue job (glue/run_ml.py), so the
cloud runs exactly the steps you tested locally. It stops at the first step that fails.

Usage (from the repo root, with .venv active and logged in to AWS):
    python scripts/run_ml_pipeline.py
"""

from __future__ import annotations

import runpy
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

STEPS = [
    ("seller report cards", "build_seller_features.py"),
    ("seller queue backtest", "backtest_seller_risk.py"),
    ("revenue forecast", "backtest_forecast.py"),
    ("drift check", "check_drift.py"),
    ("checkout risk model", "backtest_order_risk.py"),
    ("checkout reasons (SHAP)", "explain_order_risk.py"),
    ("publish to Athena", "publish_ml_outputs.py"),
]


def main() -> None:
    started = time.time()
    for number, (label, script) in enumerate(STEPS, start=1):
        print(f"\n===== Step {number}/{len(STEPS)}: {label} ({script}) =====", flush=True)
        step_started = time.time()
        try:
            runpy.run_path(str(SCRIPTS / script), run_name="__main__")
        except Exception:
            print(f"\nFAILED at step {number}: {label}. Later steps were not run.", flush=True)
            raise
        print(f"----- done in {time.time() - step_started:.0f}s", flush=True)
    print(f"\nML pipeline finished: {len(STEPS)} steps in {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()   # no sys.exit(): AWS Glue reports any SystemExit as a failed run, even a successful one