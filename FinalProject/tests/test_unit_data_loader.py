"""
Unit tests for src/data_loader.py
"""

import tempfile
from pathlib import Path
import pandas as pd
import pytest

from src.config import ALL_FEATURES, TARGET_COLUMN
from src.data_loader import load_data, get_train_val_split


@pytest.fixture
def sample_csv():
    """Generates a temporary valid CSV for data_loader testing."""
    data = {feat: [1.0, 2.0, 3.0, 4.0, 5.0] * 4 for feat in ALL_FEATURES}
    data[TARGET_COLUMN] = [0, 1, 0, 1, 0] * 4

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        pd.DataFrame(data).to_csv(f.name, index=False)
        temp_path = f.name

    yield temp_path
    Path(temp_path).unlink(missing_ok=True)


def test_load_data_valid(sample_csv):
    """Test loading valid CSV returns feature dataframe and target series."""
    X, y = load_data(sample_csv)
    assert isinstance(X, pd.DataFrame)
    assert isinstance(y, pd.Series)
    assert list(X.columns) == ALL_FEATURES
    assert len(X) == 20
    assert len(y) == 20


def test_load_data_missing_column(tmp_path):
    """Test loading CSV with missing required columns raises ValueError."""
    bad_csv = tmp_path / "bad.csv"
    pd.DataFrame({"LIMIT_BAL": [1000], "AGE": [30]}).to_csv(bad_csv, index=False)

    with pytest.raises(ValueError, match="Missing required columns"):
        load_data(str(bad_csv))


def test_get_train_val_split(sample_csv):
    """Test stratified splitting returns proportional subsets."""
    X_train, X_val, y_train, y_val = get_train_val_split(
        sample_csv, test_size=0.25, random_state=42
    )

    assert len(X_train) == 15
    assert len(X_val) == 5
    assert len(y_train) == 15
    assert len(y_val) == 5
    assert X_train.shape[1] == len(ALL_FEATURES)
