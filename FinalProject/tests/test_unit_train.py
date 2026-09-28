"""
Unit tests for src/train.py
"""

from src.train import train_baseline_model


def test_train_baseline_pipeline_execution(tmp_path, monkeypatch):
    """Test train_baseline_model pipeline execution with small estimator count."""
    monkeypatch.setattr("src.train.MODELS_DIR", tmp_path)

    # Execute training with small hyperparameters for speed
    train_baseline_model(
        n_estimators=5,
        max_depth=3,
        random_state=42,
        register_model=False,
    )

    expected_path = tmp_path / "credit_model_v1.joblib"
    assert expected_path.exists(), "Trained model artifact was not saved to expected path"
