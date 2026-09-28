"""Unit tests for the V1 model artifact."""

import os

import joblib
import pandas as pd

from credit_risk.config import get_settings
from credit_risk.data.schema import ALL_FEATURES

MODELS_DIR = get_settings().paths.models_dir


def test_model_v1_file_exists():
    model_path = os.path.join(MODELS_DIR, "credit_model_v1.joblib")
    assert os.path.exists(model_path), "Model file credit_model_v1.joblib should exist."


def test_model_v1_inference():
    model_path = os.path.join(MODELS_DIR, "credit_model_v1.joblib")
    model = joblib.load(model_path)

    # Create sample input with valid features
    sample_data = {col: [0.0] for col in ALL_FEATURES}
    sample_data["AGE"] = [35.0]
    sample_data["LIMIT_BAL"] = [50000.0]
    sample_data["SEX"] = [1]
    sample_data["EDUCATION"] = [2]
    sample_data["MARRIAGE"] = [1]

    df_sample = pd.DataFrame(sample_data)
    pred = model.predict(df_sample)
    prob = model.predict_proba(df_sample)

    assert len(pred) == 1
    assert pred[0] in [0, 1]
    assert prob.shape == (1, 2)
    assert 0.0 <= prob[0][1] <= 1.0
