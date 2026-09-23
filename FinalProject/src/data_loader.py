"""
Module: data_loader.py
Loads and validates credit default datasets.
"""

from typing import Tuple
import pandas as pd
from sklearn.model_selection import train_test_split
from src.config import ALL_FEATURES, TARGET_COLUMN


def load_data(file_path: str) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Loads dataset from CSV and splits into features X and target y.
    """
    df = pd.read_csv(file_path)

    # Verify all expected features are present
    missing_cols = [col for col in ALL_FEATURES if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in dataset: {missing_cols}")

    X = df[ALL_FEATURES].copy()
    y = df[TARGET_COLUMN].copy() if TARGET_COLUMN in df.columns else None
    return X, y


def get_train_val_split(
    file_path: str, test_size: float = 0.2, random_state: int = 42
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """
    Splits dataset into stratified training and validation sets.
    """
    X, y = load_data(file_path)
    if y is None:
        raise ValueError("Cannot split into train/val: target column missing.")

    return train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )
