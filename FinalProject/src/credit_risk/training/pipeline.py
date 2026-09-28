"""Model pipeline construction."""

from __future__ import annotations

from typing import Any

from sklearn.pipeline import Pipeline

from credit_risk.features.feature_engineering import FeatureEngineer
from credit_risk.features.preprocessing import create_preprocessor
from credit_risk.training.models import get_candidate


def build_model_pipeline(params: dict[str, Any], random_state: int, model_name: str = "random_forest") -> Pipeline:
    """Return ``FeatureEngineer -> preprocessor -> classifier`` for ``model_name``.

    The whole chain is one scikit-learn object, so the registered model applies
    exactly the same feature engineering at serving time as during training.
    """
    classifier = get_candidate(model_name).build(params, random_state)
    return Pipeline(
        steps=[
            ("features", FeatureEngineer()),
            ("preprocessor", create_preprocessor()),
            ("classifier", classifier),
        ]
    )
