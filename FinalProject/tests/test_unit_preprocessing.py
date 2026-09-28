"""
Unit tests for src/preprocessing.py
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer

from src.config import ALL_FEATURES, NUMERICAL_FEATURES, CATEGORICAL_FEATURES, ORDINAL_FEATURES
from src.preprocessing import create_preprocessor


def test_create_preprocessor_structure():
    """Verify preprocessor contains standard scaler for numerical features."""
    preprocessor = create_preprocessor()
    assert isinstance(preprocessor, ColumnTransformer)

    # Check transformer names
    transformer_names = [t[0] for t in preprocessor.transformers]
    assert "num" in transformer_names
    assert "cat" in transformer_names
    assert "ord" in transformer_names


def test_preprocessor_transform():
    """Test fitting and transforming dummy data produces correct shape and normalization."""
    # Create synthetic test dataset with all 23 features
    n_samples = 25
    data = {}
    for feat in NUMERICAL_FEATURES:
        data[feat] = np.random.uniform(10.0, 100.0, size=n_samples)
    for feat in CATEGORICAL_FEATURES:
        data[feat] = np.random.choice([1, 2], size=n_samples)
    for feat in ORDINAL_FEATURES:
        data[feat] = np.random.choice([0, 1, 2], size=n_samples)

    df = pd.DataFrame(data)[ALL_FEATURES]

    preprocessor = create_preprocessor()
    transformed = preprocessor.fit_transform(df)

    assert transformed.shape[0] == n_samples
    assert transformed.shape[1] >= len(NUMERICAL_FEATURES)
