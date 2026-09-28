"""Scoring logic shared by the predict, batch and explain endpoints.

Routes stay thin: they validate, call :class:`ScoringService`, and shape the
response. Predict and batch make exactly one vectorized ``predict_proba`` call;
explain additionally runs a bounded number of SHAP model evaluations.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np
import pandas as pd

from credit_risk.config import Settings, get_logger
from credit_risk.monitoring.metrics import BATCH_SIZE_HISTOGRAM, RollingFeatureStats, record_business_outcome
from credit_risk.responsible_ai.explainability import explain_against_reference, risk_factor_messages
from credit_risk.responsible_ai.explanations import policy_guardrails, top_risk_factors
from credit_risk.serving import database
from credit_risk.serving.decision_engine import CreditDecision, decide
from credit_risk.serving.model_loader import LoadedModel

logger = get_logger(__name__)

ExplainMethod = Literal["shap_permutation", "reference_substitution"]
EXPLAIN_METHOD_SHAP: ExplainMethod = "shap_permutation"
EXPLAIN_METHOD_SUBSTITUTION: ExplainMethod = "reference_substitution"


@dataclass(frozen=True)
class ScoreResult:
    """Model output, business decision and rule-based explanations for one applicant."""

    features: dict[str, Any]
    prediction: int
    probability: float
    outcome: CreditDecision
    utilization: float
    risk_factors: list[str]
    guardrails: dict[str, str]

    def as_fields(self) -> dict[str, Any]:
        """Keyword arguments for the ``ScoreFields`` response schemas."""
        return {
            "default_prediction": self.prediction,
            "default_probability": round(self.probability, 6),
            "credit_score": self.outcome.credit_score,
            "credit_tier": self.outcome.credit_tier,
            "risk_decision": self.outcome.decision,
            "recommended_limit_ntd": self.outcome.recommended_limit,
            "top_risk_factors": self.risk_factors,
            "policy_guardrails": self.guardrails,
        }


@dataclass(frozen=True)
class Contribution:
    """Signed effect of one feature on the default probability."""

    feature: str
    value: float
    reference_value: float
    contribution: float

    @property
    def direction(self) -> Literal["increases_risk", "decreases_risk", "neutral"]:
        """``increases_risk``, ``decreases_risk`` or ``neutral``."""
        if self.contribution > 1e-6:
            return "increases_risk"
        if self.contribution < -1e-6:
            return "decreases_risk"
        return "neutral"


def _utilization(features: dict[str, Any]) -> float:
    limit_bal = float(features["LIMIT_BAL"])
    return float(features["BILL_AMT1"]) / limit_bal if limit_bal > 0 else 0.0


def _frame(rows: list[dict[str, Any]], feature_names: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if feature_names:
        frame = frame[list(feature_names)]
    return frame


def default_probabilities(model: Any, frame: pd.DataFrame) -> np.ndarray:
    """Probability of the positive (default) class for each row."""
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(frame))
        classes = list(getattr(model, "classes_", [0, 1]))
        column = classes.index(1) if 1 in classes else proba.shape[1] - 1
        return proba[:, column].astype(float)
    return np.asarray(model.predict(frame), dtype=float)


class ScoringService:
    """Scores applicants with a model snapshot and records telemetry + inference logs."""

    def __init__(self, settings: Settings, rolling_stats: RollingFeatureStats) -> None:
        self._settings = settings
        self._rolling_stats = rolling_stats

    def _build_result(self, features: dict[str, Any], probability: float) -> ScoreResult:
        serving = self._settings.serving
        limit_bal = float(features["LIMIT_BAL"])
        age = int(features["AGE"])
        pay_0 = int(features["PAY_0"])
        utilization = _utilization(features)
        # RandomForest.predict is argmax(predict_proba): class 1 only when p1 > 0.5.
        prediction = int(probability > 0.5)
        return ScoreResult(
            features=features,
            prediction=prediction,
            probability=probability,
            outcome=decide(probability, limit_bal, serving.review_threshold, serving.decline_threshold),
            utilization=utilization,
            risk_factors=top_risk_factors(pay_0, utilization, age, limit_bal),
            guardrails=policy_guardrails(age, utilization, pay_0),
        )

    def score(self, loaded: LoadedModel, applicants: list[dict[str, Any]]) -> list[ScoreResult]:
        """Score applicants (request order preserved)."""
        probabilities = default_probabilities(loaded.model, _frame(applicants, loaded.feature_names))
        return [self._build_result(features, float(p)) for features, p in zip(applicants, probabilities, strict=True)]

    def explain(
        self, loaded: LoadedModel, applicant: dict[str, Any]
    ) -> tuple[ScoreResult, float, list[Contribution], ExplainMethod]:
        """Score one applicant and attribute its probability to its features.

        Uses permutation SHAP against the reference (median training) applicant when
        ``serving.explain.method`` is ``shap``: contributions then sum to
        ``probability - reference_probability`` and ``top_risk_factors`` is rewritten
        from them. Any SHAP failure degrades to reference substitution.

        Returns:
            ``(result, reference_probability, top-k contributions, method)``.
        """
        if self._settings.serving.explain_method == "shap":
            try:
                return self._explain_shap(loaded, applicant)
            except Exception as exc:  # Explanations must never take the endpoint down.
                logger.warning(
                    "SHAP explanation failed (%s); falling back to reference substitution.",
                    type(exc).__name__,
                    extra={"event": "explain_fallback"},
                )
        result, reference_probability, contributions = self._explain_substitution(loaded, applicant)
        return result, reference_probability, contributions, EXPLAIN_METHOD_SUBSTITUTION

    def warm_up_explainer(self, loaded: LoadedModel | None) -> None:
        """Pay SHAP's one-off import + JIT cost at startup instead of on the first request."""
        reference = self._settings.serving.explain_reference
        if loaded is None or self._settings.serving.explain_method != "shap" or not reference:
            return
        try:
            self._explain_shap(loaded, dict(reference))
        except Exception as exc:  # A failed warm-up only means the first request pays the cost.
            logger.warning("SHAP warm-up failed: %s", type(exc).__name__)

    def _explain_shap(
        self, loaded: LoadedModel, applicant: dict[str, Any]
    ) -> tuple[ScoreResult, float, list[Contribution], ExplainMethod]:
        serving = self._settings.serving
        feature_names = loaded.feature_names or tuple(applicant)
        reference = {k: v for k, v in serving.explain_reference.items() if k in applicant}
        explanation = explain_against_reference(
            loaded.model,
            applicant,
            reference,
            feature_names,
            max_evals=serving.explain_shap_max_evals,
            seed=serving.explain_seed,
        )
        contributions = [
            Contribution(
                feature=feature,
                value=float(applicant[feature]),
                reference_value=float(reference.get(feature, applicant[feature])),
                contribution=round(value, 6),
            )
            for feature, value in explanation.contributions.items()
        ]
        contributions.sort(key=lambda item: abs(item.contribution), reverse=True)
        top = contributions[: serving.explain_top_k]
        result = self._build_result(applicant, explanation.probability)
        factors = risk_factor_messages(
            [{"feature": c.feature, "value": c.value, "contribution": c.contribution} for c in contributions]
        )
        result = replace(result, risk_factors=factors or result.risk_factors)
        return result, round(explanation.reference_probability, 6), top, EXPLAIN_METHOD_SHAP

    def _explain_substitution(
        self, loaded: LoadedModel, applicant: dict[str, Any]
    ) -> tuple[ScoreResult, float, list[Contribution]]:
        """Attribute the probability by reference substitution.

        For each feature with a reference value, the applicant is re-scored with that
        feature replaced by the reference (median training applicant); the drop in
        probability is the feature's contribution. All variants go through a single
        ``predict_proba`` call.
        """
        reference = {k: v for k, v in self._settings.serving.explain_reference.items() if k in applicant}
        features = list(reference)
        rows = [applicant, {**applicant, **reference}]
        rows.extend({**applicant, feature: reference[feature]} for feature in features)
        probabilities = default_probabilities(loaded.model, _frame(rows, loaded.feature_names))

        probability = float(probabilities[0])
        reference_probability = float(probabilities[1])
        contributions = [
            Contribution(
                feature=feature,
                value=float(applicant[feature]),
                reference_value=float(reference[feature]),
                contribution=round(probability - float(p_without), 6),
            )
            for feature, p_without in zip(features, probabilities[2:], strict=True)
        ]
        contributions.sort(key=lambda item: abs(item.contribution), reverse=True)
        top = contributions[: self._settings.serving.explain_top_k]
        return self._build_result(applicant, probability), round(reference_probability, 6), top

    def record(
        self, results: list[ScoreResult], request_ids: list[str], loaded: LoadedModel, latency_ms: float
    ) -> None:
        """Update Prometheus business metrics and persist inference logs (one transaction)."""
        if len(results) > 1:
            BATCH_SIZE_HISTOGRAM.observe(len(results))
        per_item_latency = latency_ms / max(len(results), 1)
        records = []
        for result, request_id in zip(results, request_ids, strict=True):
            limit_bal = float(result.features["LIMIT_BAL"])
            record_business_outcome(
                result.outcome.decision,
                result.outcome.credit_score,
                result.outcome.recommended_limit,
                limit_bal,
                probability=result.probability,
                loss_given_default=self._settings.serving.loss_given_default,
            )
            self._rolling_stats.observe(
                result.prediction,
                int(result.features["AGE"]),
                limit_bal,
                result.utilization,
                int(result.features["PAY_0"]),
            )
            records.append(
                {
                    "request_id": request_id,
                    "features": result.features,
                    "prediction": result.prediction,
                    "probability": result.probability,
                    "risk_decision": result.outcome.decision,
                    "latency_ms": per_item_latency,
                }
            )
        database.save_inference_logs(records, model_version=loaded.version)
