"""
Module: preprocessing.py
Builds scikit-learn preprocessing pipelines for credit default features.
"""

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from src.config import NUMERICAL_FEATURES, CATEGORICAL_FEATURES, ORDINAL_FEATURES


def create_preprocessor() -> ColumnTransformer:
    """
    Constructs a ColumnTransformer that standardizes numerical features,
    one-hot encodes categorical demographics, and passes ordinal repayment status.
    """
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "num",
                StandardScaler(),
                NUMERICAL_FEATURES,
            ),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
            (
                "ord",
                "passthrough",
                ORDINAL_FEATURES,
            ),
        ],
        remainder="drop",
    )
    return preprocessor
