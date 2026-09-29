"""Domain feature engineering for credit default scoring.

All features are row-wise and stateless, so the same :class:`FeatureEngineer`
step runs identically at training time and inside the served scikit-learn
pipeline (no train/serve skew, no fitted statistics to version separately).

Time axis of the UCI columns (oldest -> latest):
``PAY_6 .. PAY_2, PAY_0`` / ``BILL_AMT6 .. BILL_AMT1`` / ``PAY_AMT6 .. PAY_AMT1``.
``PAY_AMT{i}`` settles the previous statement ``BILL_AMT{i+1}``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from credit_risk.data.schema import ALL_FEATURES

PAY_STATUS_COLUMNS = ["PAY_6", "PAY_5", "PAY_4", "PAY_3", "PAY_2", "PAY_0"]
BILL_COLUMNS = ["BILL_AMT6", "BILL_AMT5", "BILL_AMT4", "BILL_AMT3", "BILL_AMT2", "BILL_AMT1"]
PAY_AMOUNT_COLUMNS = ["PAY_AMT6", "PAY_AMT5", "PAY_AMT4", "PAY_AMT3", "PAY_AMT2", "PAY_AMT1"]

UTILIZATION_BOUNDS = (-1.0, 5.0)
PAYMENT_RATIO_BOUNDS = (0.0, 5.0)

ENGINEERED_FEATURES: list[str] = [
    "utilization_latest",
    "utilization_mean",
    "utilization_max",
    "utilization_trend",
    "payment_ratio_latest",
    "payment_ratio_mean",
    "pay_to_limit_ratio",
    "zero_payment_months",
    "delay_max",
    "delay_recent_mean",
    "delay_months",
    "delay_trend",
]


def _slope(values: np.ndarray) -> np.ndarray:
    """Least-squares slope per row of ``values`` over evenly spaced time steps (columns)."""
    steps = np.arange(values.shape[1], dtype=float)
    centered = steps - steps.mean()
    return values @ centered / float(centered @ centered)


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray, *, when_no_debt: float) -> np.ndarray:
    """``numerator / denominator`` with ``when_no_debt`` wherever the denominator is not positive."""
    result = np.full(numerator.shape, when_no_debt, dtype=float)
    positive = denominator > 0
    np.divide(numerator, denominator, out=result, where=positive)
    return result


def engineer_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return only the engineered features (``ENGINEERED_FEATURES``) for ``frame``.

    Features:
        * credit utilization: latest, mean, max and trend of ``BILL_AMT / LIMIT_BAL``;
        * payment ratio: share of the previous statement actually repaid (latest and 5-month);
        * payment capacity: mean monthly repayment over the limit, months with no repayment;
        * delinquency: worst, recent mean, count of delayed months and trend of ``PAY_*``
          (positive trend = worsening repayment behaviour).
    """
    limit = frame["LIMIT_BAL"].to_numpy(dtype=float)
    bills = frame[BILL_COLUMNS].to_numpy(dtype=float)
    payments = frame[PAY_AMOUNT_COLUMNS].to_numpy(dtype=float)
    statuses = frame[PAY_STATUS_COLUMNS].to_numpy(dtype=float)

    safe_limit = np.where(limit > 0, limit, np.nan)
    utilization = bills / safe_limit[:, None]
    utilization = np.nan_to_num(utilization, nan=0.0)

    # PAY_AMT of month t settles BILL_AMT of month t-1: pair payments[1:] with bills[:-1].
    settled_bills = bills[:, :-1]
    settling_payments = payments[:, 1:]

    # Clip in numpy and build the frame once: per-column pandas ops dominate the
    # single-row cost on the serving hot path.
    columns = {
        "utilization_latest": np.clip(utilization[:, -1], *UTILIZATION_BOUNDS),
        "utilization_mean": np.clip(utilization.mean(axis=1), *UTILIZATION_BOUNDS),
        "utilization_max": np.clip(utilization.max(axis=1), *UTILIZATION_BOUNDS),
        "utilization_trend": _slope(utilization),
        "payment_ratio_latest": np.clip(
            _safe_ratio(settling_payments[:, -1], settled_bills[:, -1], when_no_debt=1.0), *PAYMENT_RATIO_BOUNDS
        ),
        "payment_ratio_mean": np.clip(
            _safe_ratio(settling_payments.sum(axis=1), settled_bills.clip(min=0).sum(axis=1), when_no_debt=1.0),
            *PAYMENT_RATIO_BOUNDS,
        ),
        "pay_to_limit_ratio": np.nan_to_num(payments.mean(axis=1) / safe_limit, nan=0.0),
        "zero_payment_months": (payments <= 0).sum(axis=1).astype(float),
        "delay_max": statuses.max(axis=1),
        "delay_recent_mean": statuses[:, -3:].mean(axis=1),
        "delay_months": (statuses >= 1).sum(axis=1).astype(float),
        "delay_trend": _slope(statuses),
    }
    values = np.column_stack([columns[name] for name in ENGINEERED_FEATURES])
    return pd.DataFrame(values, index=frame.index, columns=ENGINEERED_FEATURES)


def add_engineered_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the 23 raw model features followed by the engineered features."""
    raw = frame[ALL_FEATURES]
    return pd.concat([raw, engineer_features(raw)], axis=1)


class FeatureEngineer(BaseEstimator, TransformerMixin):
    """Stateless scikit-learn step that appends :data:`ENGINEERED_FEATURES` to the raw features."""

    def fit(self, features: pd.DataFrame, target: Any = None) -> FeatureEngineer:
        """Record the input schema; every engineered feature is a row-wise formula.

        ``feature_names_in_`` surfaces on the enclosing ``Pipeline`` so serving can
        order request columns exactly as seen during training.
        """
        columns = features.columns if isinstance(features, pd.DataFrame) else ALL_FEATURES
        self.feature_names_in_ = np.asarray(list(columns), dtype=object)
        self.n_features_in_ = len(self.feature_names_in_)
        return self

    def transform(self, features: pd.DataFrame) -> pd.DataFrame:
        """Return raw + engineered features as a DataFrame (column names preserved)."""
        frame = features if isinstance(features, pd.DataFrame) else pd.DataFrame(features, columns=ALL_FEATURES)
        return add_engineered_features(frame)

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        """Output column names, used by downstream ``ColumnTransformer`` and explainers."""
        return np.asarray(ALL_FEATURES + ENGINEERED_FEATURES, dtype=object)
