"""Dataset loading and train/validation splitting."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN


def load_data(file_path: str | Path) -> tuple[pd.DataFrame, pd.Series | None]:
    """Load a CSV and return features ``X`` and target ``y``.

    ``y`` is ``None`` when the file has no target column (e.g. an unlabeled stream).

    Raises:
        ValueError: if any feature from the schema is missing.
    """
    df = pd.read_csv(file_path)

    missing_cols = [col for col in ALL_FEATURES if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in dataset: {missing_cols}")

    features = df[ALL_FEATURES].copy()
    target = df[TARGET_COLUMN].copy() if TARGET_COLUMN in df.columns else None
    return features, target


def get_train_val_split(
    file_path: str | Path, test_size: float = 0.2, random_state: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Split a labeled dataset into stratified training and validation sets.

    Raises:
        ValueError: if the dataset has no target column.
    """
    features, target = load_data(file_path)
    if target is None:
        raise ValueError("Cannot split into train/val: target column missing.")

    x_train, x_val, y_train, y_val = train_test_split(
        features, target, test_size=test_size, random_state=random_state, stratify=target
    )
    return x_train, x_val, y_train, y_val
