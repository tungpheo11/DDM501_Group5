"""Feature schema of the UCI Credit Card Default dataset."""

from __future__ import annotations

NUMERICAL_FEATURES: list[str] = [
    "LIMIT_BAL",
    "AGE",
    "BILL_AMT1",
    "BILL_AMT2",
    "BILL_AMT3",
    "BILL_AMT4",
    "BILL_AMT5",
    "BILL_AMT6",
    "PAY_AMT1",
    "PAY_AMT2",
    "PAY_AMT3",
    "PAY_AMT4",
    "PAY_AMT5",
    "PAY_AMT6",
]

CATEGORICAL_FEATURES: list[str] = [
    "SEX",
    "EDUCATION",
    "MARRIAGE",
]

ORDINAL_FEATURES: list[str] = [
    "PAY_0",
    "PAY_2",
    "PAY_3",
    "PAY_4",
    "PAY_5",
    "PAY_6",
]

ALL_FEATURES: list[str] = NUMERICAL_FEATURES + CATEGORICAL_FEATURES + ORDINAL_FEATURES
TARGET_COLUMN = "default_payment_next_month"
REQUEST_ID_COLUMN = "request_id"
