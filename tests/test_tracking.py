"""
Tests for MLflow experiment tracking (src/ml/tracking.py). Runs are written to a temporary folder.
"""

from src.ml.tracking import flatten, log_run


def test_flatten_turns_nested_settings_into_dotted_names():
    assert flatten({"k": 20, "lightgbm": {"params": {"num_leaves": 7}}, "cols": ["a", "b"]}) == {
        "k": "20", "lightgbm.params.num_leaves": "7", "cols": "['a', 'b']"}


def test_a_run_is_recorded_with_params_metrics_and_files(tmp_path):
    import mlflow

    folder = tmp_path / "with spaces"                 # like "Professional Stuff" on Windows
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"png")
    run_id = log_run("test_experiment", "run 1", {"k": 20}, {"holdout_wape": 0.181},
                     artifacts=[chart], tags={"winner": "avg_4w"}, mlflow_dir=folder)

    run = mlflow.get_run(run_id)
    assert run.data.params["k"] == "20"
    assert run.data.metrics["holdout_wape"] == 0.181
    assert run.data.tags["winner"] == "avg_4w"
    assert [a.path for a in mlflow.artifacts.list_artifacts(run_id=run_id)] == ["chart.png"]