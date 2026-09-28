"""
Module: fairness.py
Implements Responsible AI: Bias detection and algorithmic fairness analysis
for Credit Default Risk Scoring in accordance with Equal Credit Opportunity Act (ECOA)
and Fair Lending standards (Four-Fifths / 80% Rule).
"""

from typing import Dict, Any
import json
from pathlib import Path
import numpy as np
import pandas as pd


def compute_selection_rate(y_pred: np.ndarray) -> float:
    """Computes selection / positive prediction rate."""
    if len(y_pred) == 0:
        return 0.0
    return float(np.mean(y_pred == 0))  # In credit risk, Y=0 is APPROVE / Non-default


def disparate_impact_ratio(
    y_pred: np.ndarray,
    protected_attr: np.ndarray,
    privileged_value: Any,
    unprivileged_value: Any,
) -> float:
    """
    Computes Disparate Impact Ratio (DIR):
    DIR = Selection Rate (Unprivileged) / Selection Rate (Privileged)
    Fair lending standard: 0.80 <= DIR <= 1.25 (80% Rule).
    """
    unprivileged_mask = protected_attr == unprivileged_value
    privileged_mask = protected_attr == privileged_value

    if not np.any(unprivileged_mask) or not np.any(privileged_mask):
        return 1.0

    unprivileged_rate = compute_selection_rate(y_pred[unprivileged_mask])
    privileged_rate = compute_selection_rate(y_pred[privileged_mask])

    if privileged_rate == 0:
        return 1.0 if unprivileged_rate == 0 else 2.0

    return float(unprivileged_rate / privileged_rate)


def demographic_parity_difference(
    y_pred: np.ndarray,
    protected_attr: np.ndarray,
    privileged_value: Any,
    unprivileged_value: Any,
) -> float:
    """
    Computes Demographic Parity Difference:
    |P(Y_hat=0 | unprivileged) - P(Y_hat=0 | privileged)|
    Closer to 0.0 indicates fairer outcome across groups.
    """
    unprivileged_mask = protected_attr == unprivileged_value
    privileged_mask = protected_attr == privileged_value

    if not np.any(unprivileged_mask) or not np.any(privileged_mask):
        return 0.0

    rate_unprivileged = compute_selection_rate(y_pred[unprivileged_mask])
    rate_privileged = compute_selection_rate(y_pred[privileged_mask])
    return float(abs(rate_unprivileged - rate_privileged))


def equal_opportunity_difference(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    protected_attr: np.ndarray,
    privileged_value: Any,
    unprivileged_value: Any,
) -> float:
    """
    Computes Equal Opportunity Difference:
    Difference in True Positive Rate (TPR) between groups.
    """
    unprivileged_mask = (protected_attr == unprivileged_value) & (y_true == 0)
    privileged_mask = (protected_attr == privileged_value) & (y_true == 0)

    if not np.any(unprivileged_mask) or not np.any(privileged_mask):
        return 0.0

    tpr_unprivileged = float(np.mean(y_pred[unprivileged_mask] == 0))
    tpr_privileged = float(np.mean(y_pred[privileged_mask] == 0))
    return float(abs(tpr_unprivileged - tpr_privileged))


def evaluate_fairness(
    model: Any,
    X: pd.DataFrame,
    y: pd.Series,
) -> Dict[str, Any]:
    """
    Performs comprehensive fairness evaluation across demographic attributes:
    1. SEX (1: Male, 2: Female)
    2. EDUCATION (Higher Education vs High School/Other)
    3. AGE (Young < 30 vs Mature >= 30)
    """
    y_pred = model.predict(X)
    y_true = y.to_numpy()

    attributes_report = {}

    # 1. Gender Fairness (SEX: 1=Male, 2=Female)
    if "SEX" in X.columns:
        sex_col = X["SEX"].to_numpy()
        dir_sex = disparate_impact_ratio(
            y_pred, sex_col, privileged_value=1, unprivileged_value=2
        )
        dpd_sex = demographic_parity_difference(
            y_pred, sex_col, privileged_value=1, unprivileged_value=2
        )
        eod_sex = equal_opportunity_difference(
            y_true, y_pred, sex_col, privileged_value=1, unprivileged_value=2
        )
        attributes_report["SEX (Gender)"] = {
            "disparate_impact_ratio": round(dir_sex, 4),
            "demographic_parity_difference": round(dpd_sex, 4),
            "equal_opportunity_difference": round(eod_sex, 4),
            "four_fifths_rule_passed": bool(0.80 <= dir_sex <= 1.25),
            "privileged_group": "Male (1)",
            "unprivileged_group": "Female (2)",
        }

    # 2. Education Fairness (1,2: Graduate/University, 3: High School)
    if "EDUCATION" in X.columns:
        edu_binary = np.where(X["EDUCATION"].isin([1, 2]), 1, 0)
        dir_edu = disparate_impact_ratio(
            y_pred, edu_binary, privileged_value=1, unprivileged_value=0
        )
        dpd_edu = demographic_parity_difference(
            y_pred, edu_binary, privileged_value=1, unprivileged_value=0
        )
        attributes_report["EDUCATION (Level)"] = {
            "disparate_impact_ratio": round(dir_edu, 4),
            "demographic_parity_difference": round(dpd_edu, 4),
            "four_fifths_rule_passed": bool(0.80 <= dir_edu <= 1.25),
            "privileged_group": "University/Graduate (1,2)",
            "unprivileged_group": "High School/Other (3,4...)",
        }

    # 3. Age Fairness (< 30 vs >= 30)
    if "AGE" in X.columns:
        age_binary = np.where(X["AGE"] >= 30, 1, 0)
        dir_age = disparate_impact_ratio(
            y_pred, age_binary, privileged_value=1, unprivileged_value=0
        )
        dpd_age = demographic_parity_difference(
            y_pred, age_binary, privileged_value=1, unprivileged_value=0
        )
        attributes_report["AGE (Cohort)"] = {
            "disparate_impact_ratio": round(dir_age, 4),
            "demographic_parity_difference": round(dpd_age, 4),
            "four_fifths_rule_passed": bool(0.80 <= dir_age <= 1.25),
            "privileged_group": "Age >= 30",
            "unprivileged_group": "Age < 30",
        }

    all_passed = all(
        item.get("four_fifths_rule_passed", True)
        for item in attributes_report.values()
    )

    return {
        "status": "PASS" if all_passed else "FLAGGED_FOR_REVIEW",
        "regulatory_standard": "EEOC / CFPB Four-Fifths Rule (0.80 - 1.25)",
        "attributes": attributes_report,
        "sample_count": len(X),
    }


def generate_fairness_audit(
    model: Any,
    X: pd.DataFrame,
    y: pd.Series,
    output_path: Path = None,
) -> Dict[str, Any]:
    """Generates fairness audit and saves JSON summary artifact."""
    report = evaluate_fairness(model, X, y)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
    return report
