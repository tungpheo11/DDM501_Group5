"""Model-agnostic explanations of the default probability: SHAP (global + local) and LIME.

Explanations are computed on the **23 raw applicant fields** the API accepts, by
wrapping the whole served pipeline (feature engineering -> preprocessing -> classifier)
as ``f(x) = P(default | x)``. They therefore work for any champion algorithm and are
expressed in probability units (a SHAP value of +0.05 = +5 percentage points).

* Offline reports use a background sample of training applicants (interventional SHAP).
* ``POST /api/v1/explain`` uses a single background row, the median training applicant
  from ``configs/serving.yaml``: the SHAP base value is then exactly the reference
  applicant's probability and contributions sum to ``probability - reference_probability``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from credit_risk.data.schema import ALL_FEATURES, CATEGORICAL_FEATURES  # noqa: E402

FEATURE_LABELS: dict[str, str] = {
    "LIMIT_BAL": "credit limit",
    "SEX": "sex",
    "EDUCATION": "education level",
    "MARRIAGE": "marital status",
    "AGE": "age",
    "PAY_0": "repayment status last month",
    "PAY_2": "repayment status 2 months ago",
    "PAY_3": "repayment status 3 months ago",
    "PAY_4": "repayment status 4 months ago",
    "PAY_5": "repayment status 5 months ago",
    "PAY_6": "repayment status 6 months ago",
    **{f"BILL_AMT{i}": f"bill amount {i} month(s) ago" for i in range(1, 7)},
    **{f"PAY_AMT{i}": f"amount paid {i} month(s) ago" for i in range(1, 7)},
}
MIN_CONTRIBUTION = 1e-6


def default_probability_fn(model: Any, feature_names: Sequence[str] = ALL_FEATURES) -> Callable[[Any], np.ndarray]:
    """``f(X) -> P(default)`` for a raw feature matrix; columns follow ``feature_names``."""
    columns = list(feature_names)
    classes = list(getattr(model, "classes_", [0, 1]))
    positive = classes.index(1) if 1 in classes else -1

    def _predict(values: Any) -> np.ndarray:
        frame = values if isinstance(values, pd.DataFrame) else pd.DataFrame(np.asarray(values), columns=columns)
        return np.asarray(model.predict_proba(frame[columns]))[:, positive].astype(float)

    return _predict


def _proba_matrix_fn(model: Any, feature_names: Sequence[str]) -> Callable[[np.ndarray], np.ndarray]:
    predict = default_probability_fn(model, feature_names)

    def _predict(values: np.ndarray) -> np.ndarray:
        positive = predict(values)
        return np.column_stack([1.0 - positive, positive])

    return _predict


@dataclass
class ShapExplainer:
    """Permutation SHAP over the raw features of a fitted pipeline.

    A fresh ``shap.PermutationExplainer`` is created per :meth:`explain` call with the same
    seed, so identical inputs always get identical attributions.
    """

    model: Any
    background: pd.DataFrame
    feature_names: tuple[str, ...] = tuple(ALL_FEATURES)
    max_evals: int = 500
    seed: int = 42

    def __post_init__(self) -> None:
        minimum = 2 * len(self.feature_names) + 1
        if self.max_evals < minimum:
            raise ValueError(f"max_evals must be >= {minimum} for {len(self.feature_names)} features")

    def explain(self, frame: pd.DataFrame) -> Any:
        """Return a ``shap.Explanation`` (values, base_values, data) in probability units."""
        import shap

        columns = list(self.feature_names)
        masker = shap.maskers.Independent(self.background[columns].to_numpy(dtype=float))
        explainer = shap.PermutationExplainer(
            default_probability_fn(self.model, columns), masker, feature_names=columns, seed=self.seed
        )
        explanation = explainer(frame[columns].to_numpy(dtype=float), max_evals=self.max_evals, silent=True)
        explanation.feature_names = columns
        return explanation


def global_importance(explanation: Any) -> pd.DataFrame:
    """Mean ``|SHAP|`` per feature, sorted descending, with its share of the total."""
    values = np.abs(np.asarray(explanation.values, dtype=float))
    mean_abs = values.mean(axis=0)
    total = mean_abs.sum()
    frame = pd.DataFrame(
        {
            "feature": list(explanation.feature_names),
            "mean_abs_shap": mean_abs,
            "share": mean_abs / total if total > 0 else mean_abs,
        }
    )
    return frame.sort_values("mean_abs_shap", ascending=False, ignore_index=True)


def local_contributions(explanation: Any, index: int, top_k: int | None = None) -> list[dict[str, Any]]:
    """Signed SHAP contributions of one row, ordered by magnitude (optionally top-k)."""
    values = np.asarray(explanation.values[index], dtype=float)
    data = np.asarray(explanation.data[index], dtype=float)
    order = np.argsort(-np.abs(values))
    if top_k is not None:
        order = order[:top_k]
    names = list(explanation.feature_names)
    return [{"feature": names[i], "value": float(data[i]), "contribution": float(values[i])} for i in order]


@dataclass(frozen=True)
class ReferenceExplanation:
    """SHAP attribution of one applicant against the single reference applicant."""

    probability: float
    reference_probability: float
    contributions: dict[str, float]


def explain_against_reference(
    model: Any,
    applicant: Mapping[str, Any],
    reference: Mapping[str, float],
    feature_names: Sequence[str],
    *,
    max_evals: int = 240,
    seed: int = 42,
) -> ReferenceExplanation:
    """Baseline-Shapley values of ``applicant`` w.r.t. ``reference`` (used by ``/api/v1/explain``).

    Features without a reference value keep the applicant's value in the background, so
    they receive zero attribution.
    """
    columns = list(feature_names)
    background = pd.DataFrame([{name: reference.get(name, applicant[name]) for name in columns}])
    explainer = ShapExplainer(model, background, tuple(columns), max_evals=max_evals, seed=seed)
    explanation = explainer.explain(pd.DataFrame([{name: applicant[name] for name in columns}]))
    values = np.asarray(explanation.values[0], dtype=float)
    base = float(np.ravel(explanation.base_values)[0])
    return ReferenceExplanation(
        probability=base + float(values.sum()),
        reference_probability=base,
        contributions={name: float(value) for name, value in zip(columns, values, strict=True)},
    )


def _format_value(feature: str, value: float) -> str:
    if feature.startswith(("BILL_AMT", "PAY_AMT")) or feature == "LIMIT_BAL":
        return f"{value:,.0f} NTD"
    return f"{value:g}"


def risk_factor_messages(contributions: Sequence[Mapping[str, Any]], limit: int = 3) -> list[str]:
    """Human-readable drivers of the score, strongest first; risk-increasing factors lead.

    Example: ``"PAY_0 = 2 (repayment status last month) increases default risk by +8.4 pp"``.
    """
    ranked = sorted(
        (item for item in contributions if abs(float(item["contribution"])) > MIN_CONTRIBUTION),
        key=lambda item: (float(item["contribution"]) <= 0, -abs(float(item["contribution"]))),
    )
    messages = []
    for item in ranked[:limit]:
        feature, contribution = str(item["feature"]), float(item["contribution"])
        verb = "increases" if contribution > 0 else "decreases"
        label = FEATURE_LABELS.get(feature, feature)
        messages.append(
            f"{feature} = {_format_value(feature, float(item['value']))} ({label}) "
            f"{verb} default risk by {contribution * 100:+.1f} pp"
        )
    return messages


# --- LIME ---------------------------------------------------------------------


def lime_explain(
    model: Any,
    training_frame: pd.DataFrame,
    instance: pd.Series,
    *,
    feature_names: Sequence[str] = ALL_FEATURES,
    num_features: int = 10,
    num_samples: int = 5000,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """LIME weights for ``P(default)`` of one applicant, strongest first.

    Returns:
        ``[{"feature", "rule", "weight"}]`` where ``rule`` is LIME's discretized condition
        (e.g. ``"PAY_0 > 0.00"``) and ``weight`` its local linear coefficient.
    """
    from lime.lime_tabular import LimeTabularExplainer

    columns = list(feature_names)
    explainer = LimeTabularExplainer(
        training_data=training_frame[columns].to_numpy(dtype=float),
        feature_names=columns,
        class_names=["no_default", "default"],
        categorical_features=[columns.index(name) for name in CATEGORICAL_FEATURES if name in columns],
        mode="classification",
        discretize_continuous=True,
        random_state=seed,
    )
    result = explainer.explain_instance(
        instance[columns].to_numpy(dtype=float),
        _proba_matrix_fn(model, columns),
        labels=(1,),
        num_features=num_features,
        num_samples=num_samples,
    )
    rules = dict(result.as_list(label=1))
    weights = result.as_map()[1]
    rule_by_index = {index: rule for (index, _), rule in zip(weights, rules, strict=True)}
    return [
        {"feature": columns[index], "rule": rule_by_index[index], "weight": float(weight)} for index, weight in weights
    ]


def rank_agreement(
    shap_items: Sequence[Mapping[str, Any]], lime_items: Sequence[Mapping[str, Any]], k: int = 5
) -> dict[str, float]:
    """Top-k overlap and sign agreement between SHAP contributions and LIME weights.

    ``overlap_at_k`` is the share of SHAP's top-k features also in LIME's top-k;
    ``sign_agreement`` is the share of shared features whose effect has the same direction.
    """
    shap_top = {str(item["feature"]): float(item["contribution"]) for item in list(shap_items)[:k]}
    lime_top = {str(item["feature"]): float(item["weight"]) for item in list(lime_items)[:k]}
    shared = set(shap_top) & set(lime_top)
    same_sign = [np.sign(shap_top[name]) == np.sign(lime_top[name]) for name in shared]
    return {
        "k": k,
        "overlap_at_k": len(shared) / k if k else 0.0,
        "sign_agreement": float(np.mean(same_sign)) if same_sign else 0.0,
    }


# --- Plots --------------------------------------------------------------------


def _save(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close("all")
    return path


def plot_shap_summary(explanation: Any, path: Path, max_display: int = 15) -> Path:
    """SHAP beeswarm: per-applicant contributions coloured by feature value."""
    import shap

    shap.plots.beeswarm(explanation, max_display=max_display, show=False)
    plt.title("SHAP summary — impact on P(default)")
    return _save(path)


def plot_shap_bar(explanation: Any, path: Path, max_display: int = 15) -> Path:
    """Global importance: mean ``|SHAP|`` per feature."""
    import shap

    shap.plots.bar(explanation, max_display=max_display, show=False)
    plt.title("SHAP global importance — mean |contribution| to P(default)")
    return _save(path)


def plot_shap_waterfall(explanation: Any, path: Path, title: str, max_display: int = 12) -> Path:
    """Local waterfall of one applicant (``explanation`` is a single-row explanation)."""
    import shap

    shap.plots.waterfall(explanation, max_display=max_display, show=False)
    plt.title(title)
    return _save(path)


def plot_lime(items: Sequence[Mapping[str, Any]], path: Path, title: str) -> Path:
    """Horizontal bar chart of LIME weights (red = raises default risk)."""
    ordered = list(items)[::-1]
    weights = [float(item["weight"]) for item in ordered]
    colors = ["#d62728" if weight > 0 else "#1f77b4" for weight in weights]
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.45 * len(ordered))))
    ax.barh([str(item["rule"]) for item in ordered], weights, color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("LIME weight on P(default)")
    ax.set_title(title)
    del fig
    return _save(path)
