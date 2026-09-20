"""
Data validation stage — the quality gate in front of training.

TODO: Complete the three level functions and the orchestrator.
"""

import logging
from typing import Any, Dict, List

import pandas as pd

from pipeline.config import (
    MAX_MISSING_FRACTION,
    MAX_POSITIVE_RATE,
    MIN_POSITIVE_RATE,
    MIN_ROWS,
    RAW_FEATURES,
    TARGET,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataValidationError(Exception):
    """Raised when the dataset fails a check that must not be ignored."""


# Value domains, from the dataset documentation. (PROVIDED)
DOMAINS: Dict[str, Any] = {
    "SEX": {1, 2},
    "EDUCATION": {1, 2, 3, 4},
    "MARRIAGE": {1, 2, 3},
}
RANGES: Dict[str, tuple] = {
    "LIMIT_BAL": (10_000, 2_000_000),
    "AGE": (18, 100),
    **{c: (-2, 8) for c in ["PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"]},
}


# =============================================================================
# TODO 1: Implement validate_schema — level 1
# =============================================================================
def validate_schema(df: pd.DataFrame) -> List[str]:
    """Level 1 — are the expected columns present, with usable types?"""
    errors = []
    expected = RAW_FEATURES + [TARGET]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        errors.append(f"missing columns: {missing}")
    for c in expected:
        if c in df.columns and not pd.api.types.is_numeric_dtype(df[c]):
            errors.append(f"column '{c}' is not numeric (dtype={df[c].dtype})")
    return errors


# =============================================================================
# TODO 2: Implement validate_statistics — level 2
# =============================================================================
def validate_statistics(df: pd.DataFrame) -> List[str]:
    """Level 2 — is the shape of the data what training assumes?"""
    errors = []
    if len(df) < MIN_ROWS:
        errors.append(f"too few rows: {len(df)} < {MIN_ROWS}")
    for col in df.columns:
        frac = df[col].isna().mean()
        if frac > MAX_MISSING_FRACTION:
            errors.append(
                f"column '{col}' has {frac:.1%} missing values (max {MAX_MISSING_FRACTION:.1%})"
            )
    if TARGET in df.columns:
        rate = df[TARGET].mean()
        if rate < MIN_POSITIVE_RATE:
            errors.append(
                f"positive rate {rate:.4f} below minimum {MIN_POSITIVE_RATE}"
            )
        if rate > MAX_POSITIVE_RATE:
            errors.append(
                f"positive rate {rate:.4f} above maximum {MAX_POSITIVE_RATE}"
            )
    return errors


# =============================================================================
# TODO 3: Implement validate_semantics — level 3
# =============================================================================
def validate_semantics(df: pd.DataFrame) -> List[str]:
    """Level 3 — do the values mean what the business says they mean?"""
    errors = []
    for col, allowed in DOMAINS.items():
        if col in df.columns:
            bad_mask = ~df[col].isin(allowed)
            if bad_mask.any():
                bad_vals = sorted(df.loc[bad_mask, col].unique().tolist())
                errors.append(
                    f"column '{col}' has out-of-domain values: {bad_vals}"
                )
    for col, (lo, hi) in RANGES.items():
        if col in df.columns:
            bad_mask = (df[col] < lo) | (df[col] > hi)
            if bad_mask.any():
                errors.append(
                    f"column '{col}' has values outside [{lo}, {hi}]:"
                    f" min={df[col].min()}, max={df[col].max()}"
                )
    pay_amt_cols = [c for c in df.columns if c.startswith("PAY_AMT")]
    for col in pay_amt_cols:
        if (df[col] < 0).any():
            errors.append(f"column '{col}' contains negative values")
    return errors


# =============================================================================
# TODO 4: Implement validate_dataset
# =============================================================================
def validate_dataset(df: pd.DataFrame, raise_on_error: bool = True) -> Dict[str, Any]:
    """Run all three levels and return a report."""
    schema_errors = validate_schema(df)
    statistical_errors = validate_statistics(df)
    semantic_errors = validate_semantics(df)

    all_errors = schema_errors + statistical_errors + semantic_errors
    for err in all_errors:
        logger.error(err)

    report: Dict[str, Any] = {
        "passed": len(all_errors) == 0,
        "n_rows": int(len(df)),
        "n_columns": int(df.shape[1]),
        "schema_errors": schema_errors,
        "statistical_errors": statistical_errors,
        "semantic_errors": semantic_errors,
        "n_errors": len(all_errors),
    }

    if all_errors and raise_on_error:
        raise DataValidationError(
            f"Dataset failed validation with {len(all_errors)} error(s): {all_errors}"
        )

    return report
