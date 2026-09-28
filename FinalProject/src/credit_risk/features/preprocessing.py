"""Scikit-learn preprocessing for the credit default features."""

from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from credit_risk.data.schema import CATEGORICAL_FEATURES, NUMERICAL_FEATURES, ORDINAL_FEATURES
from credit_risk.features.feature_engineering import ENGINEERED_FEATURES, FeatureEngineer


def create_preprocessor(include_engineered: bool = True) -> ColumnTransformer:
    """Build the column transformer.

    Numerical (and, when ``include_engineered``, engineered) features are
    standardized, categorical demographics are one-hot encoded (unknown
    categories ignored) and ordinal repayment statuses pass through.
    ``include_engineered=True`` expects the output of :class:`FeatureEngineer`.
    """
    numerical = NUMERICAL_FEATURES + (ENGINEERED_FEATURES if include_engineered else [])
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), numerical),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
            ("ord", "passthrough", ORDINAL_FEATURES),
        ],
        remainder="drop",
    )


def create_feature_pipeline() -> Pipeline:
    """``FeatureEngineer -> preprocessor``: raw 23 UCI columns in, model matrix out."""
    return Pipeline(steps=[("features", FeatureEngineer()), ("preprocessor", create_preprocessor())])
