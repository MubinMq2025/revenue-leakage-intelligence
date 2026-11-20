"""
Tests for the ML pipeline runner and the Glue code bundle.
"""

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_every_pipeline_step_exists_and_publishing_comes_last():
    from scripts.run_ml_pipeline import STEPS

    for _, script in STEPS:
        assert (REPO_ROOT / "scripts" / script).exists(), script
    assert STEPS[-1][1] == "publish_ml_outputs.py"


def test_bundle_has_the_code_and_settings_but_no_data_or_caches(tmp_path):
    from scripts.build_ml_bundle import build

    build(tmp_path / "ml_bundle.zip")
    names = zipfile.ZipFile(tmp_path / "ml_bundle.zip").namelist()
    assert {"src/ml/order_risk.py", "scripts/run_ml_pipeline.py", "config/ml.yaml", "config/ml_tables.yaml"} <= set(names)
    assert not [n for n in names if n.startswith(("data/", "tests/")) or "__pycache__" in n]


def test_tracking_can_be_switched_off(monkeypatch):
    from src.ml.tracking import log_run

    monkeypatch.setenv("RLI_TRACKING", "off")
    assert log_run("x", "y", params={}, metrics={}) == "off"