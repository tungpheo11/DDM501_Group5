"""
Preprocessing and feature engineering.

Two things happen here, and keeping them straight matters:

  add_derived_features  works on the DataFrame and encodes DOMAIN knowledge —
                        ratios and counts a credit analyst would compute by hand.
  build_preprocessor    returns an unfitted sklearn transformer that is part of
                        the model Pipeline, so scaling and encoding are FITTED ON
                        TRAINING DATA ONLY and travel with the model.

TODO: Complete add_derived_features and build_preprocessor.
"""

import logging
from typing import List

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from pipeline.config import (
    BILL_FEATURES,
    CATEGORICAL_FEATURES,
    PAY_AMT_FEATURES,
    PAY_FEATURES,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# TODO 1: Implement add_derived_features
# =============================================================================
def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the six engineered features listed in config.DERIVED_FEATURES."""
    out = df.copy()
    avg_bill = out[BILL_FEATURES].mean(axis=1)
    avg_pay = out[PAY_AMT_FEATURES].mean(axis=1)
    limit_safe = out["LIMIT_BAL"].replace(0, np.nan)

    out["utilisation_ratio"] = (avg_bill / limit_safe).clip(0, 5)
    out["payment_ratio"] = (
        out["PAY_AMT1"] / out["BILL_AMT1"].replace(0, np.nan)
    ).clip(0, 5)
    out["max_delay"] = out[PAY_FEATURES].max(axis=1)
    out["n_months_delayed"] = (out[PAY_FEATURES] > 0).sum(axis=1)
    out["avg_bill_amt"] = avg_bill
    out["avg_pay_amt"] = avg_pay
    return out


# =============================================================================
# TODO 2: Implement build_preprocessor
# =============================================================================
def build_preprocessor(feature_columns: List[str]) -> ColumnTransformer:
    """Unfitted transformer: one-hot the categoricals, impute and scale the rest."""
    cat_cols = [c for c in CATEGORICAL_FEATURES if c in feature_columns]
    num_cols = [c for c in feature_columns if c not in cat_cols]

    cat_pipe = Pipeline([
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    num_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])

    transformers = []
    if cat_cols:
        transformers.append(("cat", cat_pipe, cat_cols))
    if num_cols:
        transformers.append(("num", num_pipe, num_cols))

    return ColumnTransformer(transformers=transformers, remainder="drop")


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """The full feature step: derive, then drop nothing and let the model decide."""
    return add_derived_features(df)
