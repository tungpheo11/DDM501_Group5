"""Pandera data contracts for raw, labeled, unlabeled and engineered datasets.

Every training entrypoint validates its inputs first so dirty data fails fast
with a readable report instead of silently producing a degraded model.
Domains follow the UCI Credit Card Default data dictionary as curated in
``data/raw/credit_default.csv``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.errors import SchemaErrors

from credit_risk.data.schema import ALL_FEATURES, ORDINAL_FEATURES, REQUEST_ID_COLUMN, TARGET_COLUMN

BILL_COLUMNS = [f"BILL_AMT{i}" for i in range(1, 7)]
PAY_AMT_COLUMNS = [f"PAY_AMT{i}" for i in range(1, 7)]

MAX_CREDIT_AMOUNT = 10_000_000.0
MIN_TARGET_RATE = 0.10
MAX_TARGET_RATE = 0.40
MAX_FAILURE_EXAMPLES = 20


class DataValidationError(ValueError):
    """Raised when a dataset violates its data contract."""

    def __init__(self, dataset: str, failures: list[dict[str, Any]], total_failures: int) -> None:
        self.dataset = dataset
        self.failures = failures
        self.total_failures = total_failures
        preview = "; ".join(f"{f['column']}: {f['check']} (e.g. {f['failure_case']})" for f in failures[:5])
        super().__init__(f"Dataset '{dataset}' failed validation with {total_failures} violation(s): {preview}")


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of validating one dataset."""

    dataset: str
    rows: int
    passed: bool
    total_failures: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    target_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation."""
        return {
            "dataset": self.dataset,
            "rows": self.rows,
            "passed": self.passed,
            "total_failures": self.total_failures,
            "target_rate": self.target_rate,
            "failures": self.failures,
        }


def _feature_columns() -> dict[str, pa.Column]:
    columns: dict[str, pa.Column] = {
        "LIMIT_BAL": pa.Column(float, pa.Check.in_range(0, MAX_CREDIT_AMOUNT, include_min=False), coerce=True),
        "SEX": pa.Column(int, pa.Check.isin([1, 2]), coerce=True),
        "EDUCATION": pa.Column(int, pa.Check.isin([1, 2, 3, 4]), coerce=True),
        "MARRIAGE": pa.Column(int, pa.Check.isin([1, 2, 3]), coerce=True),
        "AGE": pa.Column(int, pa.Check.in_range(18, 100), coerce=True),
    }
    for name in ORDINAL_FEATURES:
        columns[name] = pa.Column(int, pa.Check.in_range(-2, 9), coerce=True)
    for name in BILL_COLUMNS:
        columns[name] = pa.Column(float, pa.Check.in_range(-MAX_CREDIT_AMOUNT, MAX_CREDIT_AMOUNT), coerce=True)
    for name in PAY_AMT_COLUMNS:
        columns[name] = pa.Column(float, pa.Check.in_range(0, MAX_CREDIT_AMOUNT), coerce=True)
    return columns


def _target_rate_check(min_rate: float, max_rate: float) -> pa.Check:
    return pa.Check(
        lambda series: min_rate <= float(series.mean()) <= max_rate,
        element_wise=False,
        error=f"positive-class rate outside [{min_rate:.2f}, {max_rate:.2f}]",
        name="target_balance",
    )


def build_feature_schema(name: str = "features") -> pa.DataFrameSchema:
    """Schema for scoring inputs: the 23 model features, extra columns allowed."""
    return pa.DataFrameSchema(_feature_columns(), name=name, strict=False, coerce=True)


def build_labeled_schema(
    name: str = "labeled",
    min_target_rate: float = MIN_TARGET_RATE,
    max_target_rate: float = MAX_TARGET_RATE,
) -> pa.DataFrameSchema:
    """Schema for training data: features plus a binary target with a plausible class balance."""
    columns = _feature_columns()
    columns[TARGET_COLUMN] = pa.Column(
        int,
        [pa.Check.isin([0, 1]), _target_rate_check(min_target_rate, max_target_rate)],
        coerce=True,
    )
    return pa.DataFrameSchema(columns, name=name, strict=False, coerce=True)


def build_stream_schema(name: str = "unlabeled_stream") -> pa.DataFrameSchema:
    """Schema for unlabeled production traffic keyed by a unique ``request_id``."""
    columns = _feature_columns()
    columns[REQUEST_ID_COLUMN] = pa.Column(str, unique=True, coerce=True)
    return pa.DataFrameSchema(columns, name=name, strict=False, coerce=True)


def build_ground_truth_schema(name: str = "ground_truth") -> pa.DataFrameSchema:
    """Schema for delayed labels joined to the drifted stream by ``request_id``."""
    return pa.DataFrameSchema(
        {
            REQUEST_ID_COLUMN: pa.Column(str, unique=True, coerce=True),
            TARGET_COLUMN: pa.Column(int, pa.Check.isin([0, 1]), coerce=True),
        },
        name=name,
        strict=True,
        coerce=True,
    )


def build_engineered_schema(feature_names: Iterable[str], name: str = "engineered") -> pa.DataFrameSchema:
    """Schema for the model matrix after feature engineering: finite numbers only."""
    finite = pa.Check(lambda series: pd.Series(np.isfinite(series.astype(float)), index=series.index), name="finite")
    columns = {col: pa.Column(float, finite, coerce=True) for col in feature_names}
    return pa.DataFrameSchema(columns, name=name, strict=False, coerce=True)


def _summarise(exc: SchemaErrors) -> tuple[list[dict[str, Any]], int]:
    cases = exc.failure_cases
    examples = [
        {
            "column": None if pd.isna(row["column"]) else str(row["column"]),
            "check": str(row["check"]),
            "failure_case": None if pd.isna(row["failure_case"]) else str(row["failure_case"]),
            "index": None if pd.isna(row["index"]) else int(row["index"]),
        }
        for _, row in cases.head(MAX_FAILURE_EXAMPLES).iterrows()
    ]
    return examples, int(len(cases))


def validate_frame(frame: pd.DataFrame, schema: pa.DataFrameSchema) -> pd.DataFrame:
    """Validate ``frame`` lazily (collect every violation) and return the coerced frame.

    Raises:
        DataValidationError: listing up to ``MAX_FAILURE_EXAMPLES`` failure cases.
    """
    try:
        return schema.validate(frame, lazy=True)
    except SchemaErrors as exc:
        failures, total = _summarise(exc)
        raise DataValidationError(schema.name or "dataset", failures, total) from exc


def check_frame(frame: pd.DataFrame, schema: pa.DataFrameSchema) -> ValidationReport:
    """Validate without raising and return a :class:`ValidationReport`."""
    target_rate = float(frame[TARGET_COLUMN].mean()) if TARGET_COLUMN in frame.columns else None
    try:
        validate_frame(frame, schema)
    except DataValidationError as exc:
        return ValidationReport(
            dataset=exc.dataset,
            rows=len(frame),
            passed=False,
            total_failures=exc.total_failures,
            failures=exc.failures,
            target_rate=target_rate,
        )
    return ValidationReport(dataset=schema.name or "dataset", rows=len(frame), passed=True, target_rate=target_rate)


def validate_training_frame(frame: pd.DataFrame, name: str = "training") -> pd.DataFrame:
    """Validate a labeled training frame and return only features + target."""
    validated = validate_frame(frame, build_labeled_schema(name))
    return validated[ALL_FEATURES + [TARGET_COLUMN]]


def validate_feature_frame(frame: pd.DataFrame, name: str = "features") -> pd.DataFrame:
    """Validate scoring inputs and return the 23 model features."""
    return validate_frame(frame, build_feature_schema(name))[ALL_FEATURES]


def dataset_schemas() -> dict[str, pa.DataFrameSchema]:
    """Schema of every versioned dataset, keyed by its path relative to ``data/``."""
    return {
        "raw/credit_default.csv": build_labeled_schema("raw/credit_default.csv"),
        "reference/train_baseline.csv": build_labeled_schema("reference/train_baseline.csv"),
        "processed/stream_normal.csv": build_labeled_schema("processed/stream_normal.csv"),
        "processed/stream_drifted.csv": build_stream_schema("processed/stream_drifted.csv"),
        "processed/ground_truth_feedback.csv": build_ground_truth_schema("processed/ground_truth_feedback.csv"),
    }


def validate_data_directory(data_dir: Path) -> list[ValidationReport]:
    """Validate every dataset listed in :func:`dataset_schemas` that exists under ``data_dir``."""
    reports = []
    for relative_path, schema in dataset_schemas().items():
        path = data_dir / relative_path
        if path.exists():
            reports.append(check_frame(pd.read_csv(path), schema))
    return reports


__all__ = [
    "DataValidationError",
    "ValidationReport",
    "build_engineered_schema",
    "build_feature_schema",
    "build_ground_truth_schema",
    "build_labeled_schema",
    "build_stream_schema",
    "check_frame",
    "dataset_schemas",
    "validate_data_directory",
    "validate_feature_frame",
    "validate_frame",
    "validate_training_frame",
]
