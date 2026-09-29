"""Group fairness audit and bias mitigation for the credit default model (Fairlearn).

Conventions:

* The model predicts **default** (class 1). ``selection_rate`` is therefore the share of
  cardholders flagged as defaulters, and ``approval_rate`` is its complement under the
  3-way serving policy (``APPROVE`` below the review threshold).
* Demographic parity difference (DPD) and equalized odds difference (EOD) are computed
  on the binary decision at ``decision_threshold``; DPD on "flagged as default" equals
  DPD on "approved" because one is ``1 -`` the other.
* ``age_group`` is derived from ``AGE``; demographic codes are mapped to readable labels
  so reports never need the UCI code book.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from fairlearn.metrics import (
    MetricFrame,
    demographic_parity_difference,
    demographic_parity_ratio,
    equalized_odds_difference,
    false_negative_rate,
    false_positive_rate,
    selection_rate,
    true_positive_rate,
)
from fairlearn.postprocessing import ThresholdOptimizer
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

from credit_risk.evaluation.business_cost import expected_financial_loss

SENSITIVE_ATTRIBUTES: tuple[str, ...] = ("SEX", "age_group", "EDUCATION", "MARRIAGE")
PROTECTED_COLUMNS: tuple[str, ...] = ("SEX", "AGE", "EDUCATION", "MARRIAGE")

AGE_BINS: tuple[int, ...] = (0, 29, 39, 49, 200)
AGE_LABELS: tuple[str, ...] = ("<30", "30-39", "40-49", "50+")

GROUP_LABELS: dict[str, dict[int, str]] = {
    "SEX": {1: "male", 2: "female"},
    "EDUCATION": {1: "graduate_school", 2: "university", 3: "high_school", 4: "others", 5: "unknown", 6: "unknown"},
    "MARRIAGE": {1: "married", 2: "single", 3: "others"},
}
UNKNOWN_LABEL = "unknown"


def age_group(age: pd.Series | Sequence[float]) -> pd.Series:
    """Bucket ``AGE`` into ``<30``, ``30-39``, ``40-49`` and ``50+``."""
    series = pd.Series(age)
    grouped = pd.cut(series, bins=list(AGE_BINS), labels=list(AGE_LABELS))
    return grouped.astype(str).rename("age_group")


def sensitive_frame(features: pd.DataFrame) -> pd.DataFrame:
    """Readable sensitive attributes (``SEX``, ``age_group``, ``EDUCATION``, ``MARRIAGE``) for each row."""
    frame = pd.DataFrame(index=features.index)
    for column in ("SEX", "EDUCATION", "MARRIAGE"):
        mapping = GROUP_LABELS[column]
        frame[column] = features[column].map(lambda code, m=mapping: m.get(int(code), UNKNOWN_LABEL))
    frame["age_group"] = age_group(features["AGE"]).to_numpy()
    return frame[list(SENSITIVE_ATTRIBUTES)]


def approval_decisions(y_prob: np.ndarray, review_threshold: float, decline_threshold: float) -> np.ndarray:
    """``APPROVE`` / ``REVIEW`` / ``DECLINE`` per cardholder, mirroring the serving decision engine."""
    probs = np.asarray(y_prob, dtype=float)
    return np.where(probs >= decline_threshold, "DECLINE", np.where(probs >= review_threshold, "REVIEW", "APPROVE"))


def _base_rate(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(y_true)) if len(y_true) else float("nan")


def _group_roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return float("nan")
    return float(roc_auc_score(y_true, y_score))


def _loss_metric(cost_fn: float, cost_fp: float) -> Callable[[np.ndarray, np.ndarray], float]:
    def _expected_loss(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        return expected_financial_loss(y_true, y_pred, cost_fn, cost_fp)

    return _expected_loss


def _max_gap(values: pd.Series) -> float:
    clean = values.dropna()
    return float(clean.max() - clean.min()) if len(clean) else float("nan")


def _min_ratio(values: pd.Series) -> float:
    clean = values.dropna()
    if not len(clean) or clean.max() <= 0:
        return float("nan")
    return float(clean.min() / clean.max())


@dataclass(frozen=True)
class FairnessThresholds:
    """Tolerances used to flag an attribute (``PASS`` / ``WARN``)."""

    demographic_parity_difference: float = 0.10
    equalized_odds_difference: float = 0.10
    disparate_impact_ratio: float = 0.80


def audit_attribute(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    sensitive: pd.Series,
    *,
    threshold: float = 0.5,
    review_threshold: float = 0.30,
    decline_threshold: float = 0.60,
    cost_fn: float = 10.0,
    cost_fp: float = 1.0,
    tolerances: FairnessThresholds | None = None,
) -> dict[str, Any]:
    """Per-group metrics and disparity summary for one sensitive attribute.

    Returns:
        ``{"attribute", "groups": [...], "summary": {...}, "status", "violations"}``. Group rows
        hold count, default base rate, selection (flagged) rate, approval/review/decline rates,
        TPR, FPR, FNR, ROC-AUC and expected loss. The summary holds DPD, demographic parity
        ratio, EOD, approval-rate gap and the disparate impact ratio of approval rates.
    """
    tolerances = tolerances or FairnessThresholds()
    labels = np.asarray(y_true, dtype=int)
    probs = np.asarray(y_prob, dtype=float)
    preds = (probs >= threshold).astype(int)
    groups = pd.Series(np.asarray(sensitive), name=str(sensitive.name))
    decisions = approval_decisions(probs, review_threshold, decline_threshold)

    frame = MetricFrame(
        metrics={
            "base_rate": _base_rate,
            "selection_rate": selection_rate,
            "tpr": true_positive_rate,
            "fpr": false_positive_rate,
            "fnr": false_negative_rate,
            "expected_loss": _loss_metric(cost_fn, cost_fp),
        },
        y_true=labels,
        y_pred=preds,
        sensitive_features=groups,
    )
    by_group = frame.by_group.copy()
    by_group["count"] = groups.value_counts().reindex(by_group.index).astype(int)
    by_group["roc_auc"] = [
        _group_roc_auc(labels[(groups == group).to_numpy()], probs[(groups == group).to_numpy()])
        for group in by_group.index
    ]
    for decision in ("APPROVE", "REVIEW", "DECLINE"):
        column = f"{decision.lower()}_rate"
        by_group[column] = [
            float(np.mean(decisions[(groups == group).to_numpy()] == decision)) for group in by_group.index
        ]

    summary = {
        "demographic_parity_difference": float(demographic_parity_difference(labels, preds, sensitive_features=groups)),
        "demographic_parity_ratio": float(demographic_parity_ratio(labels, preds, sensitive_features=groups)),
        "equalized_odds_difference": float(equalized_odds_difference(labels, preds, sensitive_features=groups)),
        "tpr_difference": _max_gap(by_group["tpr"]),
        "fpr_difference": _max_gap(by_group["fpr"]),
        "approval_rate_difference": _max_gap(by_group["approve_rate"]),
        "disparate_impact_ratio": _min_ratio(by_group["approve_rate"]),
        "roc_auc_difference": _max_gap(by_group["roc_auc"]),
    }
    violations = []
    if summary["demographic_parity_difference"] > tolerances.demographic_parity_difference:
        violations.append("demographic_parity_difference")
    if summary["equalized_odds_difference"] > tolerances.equalized_odds_difference:
        violations.append("equalized_odds_difference")
    if summary["disparate_impact_ratio"] < tolerances.disparate_impact_ratio:
        violations.append("disparate_impact_ratio")

    columns = [
        "count",
        "base_rate",
        "selection_rate",
        "approve_rate",
        "review_rate",
        "decline_rate",
        "tpr",
        "fpr",
        "fnr",
        "roc_auc",
        "expected_loss",
    ]
    ordered = sorted(by_group.index, key=group_sort_key)
    rows = [
        {"group": str(group), **{key: _clean(value) for key, value in by_group.loc[group, columns].items()}}
        for group in ordered
    ]
    for row in rows:
        row["count"] = int(row["count"])
    return {
        "attribute": str(sensitive.name),
        "groups": rows,
        "summary": {key: _clean(value) for key, value in summary.items()},
        "status": "WARN" if violations else "PASS",
        "violations": violations,
    }


def audit_fairness(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    sensitive: pd.DataFrame,
    attributes: Sequence[str] = SENSITIVE_ATTRIBUTES,
    **kwargs: Any,
) -> dict[str, dict[str, Any]]:
    """Run :func:`audit_attribute` for every attribute in ``attributes`` (keyword args forwarded)."""
    return {attribute: audit_attribute(y_true, y_prob, sensitive[attribute], **kwargs) for attribute in attributes}


def group_sort_key(group: Any) -> tuple[int, str]:
    """Age bands in chronological order, everything else alphabetically."""
    label = str(group)
    return (AGE_LABELS.index(label), label) if label in AGE_LABELS else (len(AGE_LABELS), label)


def _clean(value: Any) -> Any:
    if isinstance(value, np.integer | int):
        return int(value)
    if isinstance(value, np.floating | float):
        return None if np.isnan(value) else round(float(value), 6)
    return value


# --- Mitigation ---------------------------------------------------------------


def reweighing_weights(y_true: Sequence[int] | np.ndarray, sensitive: Sequence[Any] | pd.Series) -> np.ndarray:
    """Kamiran & Calders reweighing: ``w(a, y) = P(a) * P(y) / P(a, y)``.

    After weighting, the label is statistically independent of the sensitive group in the
    training data; the mean weight is 1.
    """
    frame = pd.DataFrame({"a": np.asarray(sensitive), "y": np.asarray(y_true, dtype=int)})
    n = len(frame)
    p_a = frame["a"].map(frame["a"].value_counts() / n)
    p_y = frame["y"].map(frame["y"].value_counts() / n)
    joint = frame.groupby(["a", "y"]).size() / n
    p_ay = pd.Series(list(zip(frame["a"], frame["y"], strict=True))).map(joint)
    return (p_a.to_numpy() * p_y.to_numpy() / p_ay.to_numpy()).astype(float)


def neutralize_columns(features: pd.DataFrame, values: Mapping[str, float]) -> pd.DataFrame:
    """Return a copy of ``features`` with every column in ``values`` set to that constant."""
    frame = features.copy()
    for column, value in values.items():
        if column in frame.columns:
            frame[column] = value
    return frame


def make_unaware(model: Pipeline, neutral_values: Mapping[str, float]) -> Pipeline:
    """Wrap ``model`` so protected attributes are replaced by constants before fitting and scoring.

    This is "fairness through unawareness": the model cannot use the attributes directly,
    but may still pick them up through correlated features (proxies).
    """
    neutralizer = FunctionTransformer(neutralize_columns, kw_args={"values": dict(neutral_values)})
    return Pipeline(steps=[("neutralize", neutralizer), ("model", model)])


def fit_threshold_optimizer(
    model: Any,
    features: pd.DataFrame,
    y_true: Sequence[int] | np.ndarray,
    sensitive: Sequence[Any] | pd.Series,
    *,
    constraints: str = "equalized_odds",
    objective: str = "balanced_accuracy_score",
) -> ThresholdOptimizer:
    """Post-process a fitted model with group-specific (randomized) thresholds."""
    optimizer = ThresholdOptimizer(
        estimator=model,
        constraints=constraints,
        objective=objective,
        prefit=True,
        predict_method="predict_proba",
    )
    optimizer.fit(features, np.asarray(y_true, dtype=int), sensitive_features=np.asarray(sensitive))
    return optimizer


def threshold_optimizer_outputs(
    optimizer: ThresholdOptimizer, features: pd.DataFrame, sensitive: Sequence[Any] | pd.Series, random_state: int
) -> tuple[np.ndarray, np.ndarray]:
    """``(binary predictions, P(flagged))`` of a fitted :class:`ThresholdOptimizer`.

    Predictions are randomized between two thresholds per group; ``random_state`` makes them
    reproducible. ``P(flagged)`` is the mixing probability, used as the score for ROC-AUC.
    """
    groups = np.asarray(sensitive)
    preds = np.asarray(optimizer.predict(features, sensitive_features=groups, random_state=random_state), dtype=int)
    scores = np.asarray(optimizer._pmf_predict(features, sensitive_features=groups))[:, 1]
    return preds, scores


def evaluate_variant(
    name: str,
    y_true: Sequence[int] | np.ndarray,
    y_pred: Sequence[int] | np.ndarray,
    y_score: Sequence[float] | np.ndarray,
    sensitive: Sequence[Any] | pd.Series,
    *,
    cost_fn: float = 10.0,
    cost_fp: float = 1.0,
    description: str = "",
) -> dict[str, Any]:
    """Accuracy, fairness and business-cost metrics for one mitigation variant."""
    labels = np.asarray(y_true, dtype=int)
    preds = np.asarray(y_pred, dtype=int)
    groups = pd.Series(np.asarray(sensitive))
    approvals = pd.Series(1 - preds).groupby(groups.to_numpy()).mean()
    positives = labels == 1
    return {
        "variant": name,
        "description": description,
        "roc_auc": _clean(float(roc_auc_score(labels, np.asarray(y_score, dtype=float)))),
        "expected_loss": _clean(expected_financial_loss(labels, preds, cost_fn, cost_fp)),
        "recall": _clean(float(preds[positives].mean()) if positives.any() else float("nan")),
        "flagged_rate": _clean(float(preds.mean())),
        "demographic_parity_difference": _clean(
            float(demographic_parity_difference(labels, preds, sensitive_features=groups))
        ),
        "equalized_odds_difference": _clean(float(equalized_odds_difference(labels, preds, sensitive_features=groups))),
        "approval_rate_difference": _clean(_max_gap(approvals)),
        "disparate_impact_ratio": _clean(_min_ratio(approvals)),
    }


@dataclass(frozen=True)
class MitigationData:
    """Datasets for one mitigation experiment (``sensitive_*`` are group labels of one attribute)."""

    x_train: pd.DataFrame
    y_train: pd.Series
    x_fit: pd.DataFrame
    y_fit: pd.Series
    sensitive_fit: pd.Series
    x_test: pd.DataFrame
    y_test: pd.Series
    sensitive_test: pd.Series
    sensitive_train: pd.Series


def run_mitigation(
    champion: Any,
    build_model: Callable[[], Pipeline],
    data: MitigationData,
    *,
    threshold: float = 0.5,
    cost_fn: float = 10.0,
    cost_fp: float = 1.0,
    neutral_values: Mapping[str, float] | None = None,
    constraints: str = "equalized_odds",
    objective: str = "balanced_accuracy_score",
    random_state: int = 42,
) -> list[dict[str, Any]]:
    """Compare the champion with three mitigations on the same held-out test split.

    Variants:
        * ``champion`` — the served model at ``threshold`` (reference point);
        * ``retrained`` — same algorithm/params refit on train + fit split (control for the
          extra data the in-processing variants see, incl. the under-30 cohort);
        * ``reweighing`` — ``retrained`` with Kamiran & Calders sample weights (pre-processing);
        * ``unawareness`` — ``retrained`` with protected attributes neutralized;
        * ``threshold_optimizer`` — champion post-processed with group thresholds fitted on
          the fit split under ``constraints`` (post-processing).
    """
    kwargs = {"cost_fn": cost_fn, "cost_fp": cost_fp}
    rows: list[dict[str, Any]] = []

    def _score(model: Any) -> tuple[np.ndarray, np.ndarray]:
        scores = np.asarray(model.predict_proba(data.x_test))[:, 1]
        return (scores >= threshold).astype(int), scores

    preds, scores = _score(champion)
    rows.append(
        evaluate_variant(
            "champion",
            data.y_test,
            preds,
            scores,
            data.sensitive_test,
            description="Served champion, no mitigation",
            **kwargs,
        )
    )

    x_combined = pd.concat([data.x_train, data.x_fit])
    y_combined = pd.concat([data.y_train, data.y_fit])
    s_combined = pd.concat([data.sensitive_train, data.sensitive_fit])

    retrained = build_model().fit(x_combined, y_combined)
    preds, scores = _score(retrained)
    rows.append(
        evaluate_variant(
            "retrained",
            data.y_test,
            preds,
            scores,
            data.sensitive_test,
            description="Refit on train + fit split, no weights (control)",
            **kwargs,
        )
    )

    weights = reweighing_weights(y_combined, s_combined)
    reweighed = build_model().fit(x_combined, y_combined, classifier__sample_weight=weights)
    preds, scores = _score(reweighed)
    rows.append(
        evaluate_variant(
            "reweighing",
            data.y_test,
            preds,
            scores,
            data.sensitive_test,
            description="Refit with Kamiran & Calders weights (pre-processing)",
            **kwargs,
        )
    )

    if neutral_values:
        unaware = make_unaware(build_model(), neutral_values).fit(x_combined, y_combined)
        preds, scores = _score(unaware)
        rows.append(
            evaluate_variant(
                "unawareness",
                data.y_test,
                preds,
                scores,
                data.sensitive_test,
                description="Refit without SEX/AGE/EDUCATION/MARRIAGE (set to constants)",
                **kwargs,
            )
        )

    optimizer = fit_threshold_optimizer(
        champion, data.x_fit, data.y_fit, data.sensitive_fit, constraints=constraints, objective=objective
    )
    preds, scores = threshold_optimizer_outputs(optimizer, data.x_test, data.sensitive_test, random_state)
    rows.append(
        evaluate_variant(
            "threshold_optimizer",
            data.y_test,
            preds,
            scores,
            data.sensitive_test,
            description=f"Champion + ThresholdOptimizer ({constraints}, {objective}) (post-processing)",
            **kwargs,
        )
    )
    return rows
