"""Pydantic request/response models of the scoring API (``/api/v1``).

Request bounds follow the UCI Credit Default data dictionary with head-room for
values not seen in training; anything outside them is rejected with HTTP 422.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from credit_risk.serving import openapi_examples as ex

Decision = Literal["APPROVE", "REVIEW", "DECLINE"]
CreditTier = Literal["PRIME", "NEAR_PRIME", "SUBPRIME", "HIGH_RISK"]

_MAX_AMOUNT = 10_000_000.0
_PAY_MIN = -2
_PAY_MAX = 9
_REPAYMENT_HELP = "-2=no consumption, -1=paid in full, 0=revolving credit, 1..9=months of payment delay"


class CreditPredictRequest(BaseModel):
    """One cardholder account after its latest statement; field names follow the UCI dataset columns."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [ex.LOW_RISK_CARDHOLDER]})

    LIMIT_BAL: float = Field(..., gt=0, le=_MAX_AMOUNT, description="Current credit limit of the card (NT dollar)")
    SEX: int = Field(..., ge=1, le=2, description="Gender (1=male, 2=female)")
    EDUCATION: int = Field(
        ..., ge=0, le=6, description="Education (1=graduate, 2=university, 3=high school, 4=others, 0/5/6=unknown)"
    )
    MARRIAGE: int = Field(..., ge=0, le=3, description="Marital status (1=married, 2=single, 3=others, 0=unknown)")
    AGE: int = Field(..., ge=18, le=100, description="Age in years")
    PAY_0: int = Field(..., ge=_PAY_MIN, le=_PAY_MAX, description=f"Repayment status in September ({_REPAYMENT_HELP})")
    PAY_2: int = Field(..., ge=_PAY_MIN, le=_PAY_MAX, description="Repayment status in August")
    PAY_3: int = Field(..., ge=_PAY_MIN, le=_PAY_MAX, description="Repayment status in July")
    PAY_4: int = Field(..., ge=_PAY_MIN, le=_PAY_MAX, description="Repayment status in June")
    PAY_5: int = Field(..., ge=_PAY_MIN, le=_PAY_MAX, description="Repayment status in May")
    PAY_6: int = Field(..., ge=_PAY_MIN, le=_PAY_MAX, description="Repayment status in April")
    BILL_AMT1: float = Field(
        ..., ge=-_MAX_AMOUNT, le=_MAX_AMOUNT, description="Bill statement in September (NT dollar, may be negative)"
    )
    BILL_AMT2: float = Field(..., ge=-_MAX_AMOUNT, le=_MAX_AMOUNT, description="Bill statement in August")
    BILL_AMT3: float = Field(..., ge=-_MAX_AMOUNT, le=_MAX_AMOUNT, description="Bill statement in July")
    BILL_AMT4: float = Field(..., ge=-_MAX_AMOUNT, le=_MAX_AMOUNT, description="Bill statement in June")
    BILL_AMT5: float = Field(..., ge=-_MAX_AMOUNT, le=_MAX_AMOUNT, description="Bill statement in May")
    BILL_AMT6: float = Field(..., ge=-_MAX_AMOUNT, le=_MAX_AMOUNT, description="Bill statement in April")
    PAY_AMT1: float = Field(..., ge=0, le=_MAX_AMOUNT, description="Previous payment in September (NT dollar)")
    PAY_AMT2: float = Field(..., ge=0, le=_MAX_AMOUNT, description="Previous payment in August")
    PAY_AMT3: float = Field(..., ge=0, le=_MAX_AMOUNT, description="Previous payment in July")
    PAY_AMT4: float = Field(..., ge=0, le=_MAX_AMOUNT, description="Previous payment in June")
    PAY_AMT5: float = Field(..., ge=0, le=_MAX_AMOUNT, description="Previous payment in May")
    PAY_AMT6: float = Field(..., ge=0, le=_MAX_AMOUNT, description="Previous payment in April")


DEPRECATED_BATCH_FIELD = "applicants"


def _document_deprecated_batch_alias(schema: dict[str, Any]) -> None:
    # ``validation_alias`` choices never reach the JSON schema, so the legacy name is
    # published by hand, pointing at the same item schema and flagged as deprecated.
    properties = schema.get("properties", {})
    if "cardholders" not in properties:
        return
    legacy = {key: value for key, value in properties["cardholders"].items() if key not in {"title", "description"}}
    properties[DEPRECATED_BATCH_FIELD] = {
        **legacy,
        "title": "Applicants",
        "deprecated": True,
        "description": "Deprecated alias of `cardholders`, still accepted for backward compatibility. "
        "Send exactly one of the two fields: a request carrying both is rejected with 422.",
    }


class BatchPredictRequest(BaseModel):
    """Several cardholder accounts scored in one vectorized call (post-statement limit review)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=_document_deprecated_batch_alias)

    cardholders: list[CreditPredictRequest] = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("cardholders", DEPRECATED_BATCH_FIELD),
        description="Cardholder accounts to score; the server caps the size (see `batch_max_size`). "
        "Validation errors report the field name the client sent (`cardholders.N.FIELD` or "
        "`applicants.N.FIELD`).",
    )


class _ServedModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_version: str = Field(..., description="Registry version number, or the artifact name in fallback mode")
    served_by: str = Field(..., description="Model source: mlflow_registry or local_artifact")


class ScoreFields(BaseModel):
    """Model output plus business decision for one cardholder."""

    default_prediction: int = Field(..., description="0 = no default expected, 1 = default risk")
    default_probability: float = Field(..., ge=0.0, le=1.0, description="Probability of default (0.0 to 1.0)")
    credit_score: int = Field(..., ge=300, le=850, description="Credit score on a 300-850 scale (higher is better)")
    credit_tier: CreditTier = Field(..., description="Risk tier")
    risk_decision: Decision = Field(..., description="Business decision")
    recommended_limit_ntd: float = Field(
        ...,
        ge=0,
        description="Suggested credit limit in NT dollars: raise on APPROVE, cut on REVIEW, 0 on DECLINE "
        "(available limit frozen, outstanding balance still due)",
    )
    top_risk_factors: list[str] = Field(default_factory=list, description="Human-readable drivers of the score")
    policy_guardrails: dict[str, str] = Field(default_factory=dict, description="Deterministic compliance checks")


class PredictionResponse(ScoreFields, _ServedModel):
    """Scoring result for ``POST /api/v1/predict``."""

    model_config = ConfigDict(protected_namespaces=(), json_schema_extra={"examples": [ex.PREDICTION_RESPONSE]})

    request_id: str
    latency_ms: float


class BatchPredictionItem(ScoreFields):
    """Result for one cardholder of a batch, in request order."""

    index: int = Field(..., ge=0, description="Position of the cardholder in the request")
    request_id: str = Field(..., description="Per-item id (`<batch request id>-<index>`) stored in the inference log")


class BatchPredictionResponse(_ServedModel):
    """Scoring result for ``POST /api/v1/predict/batch``."""

    model_config = ConfigDict(protected_namespaces=(), json_schema_extra={"examples": [ex.BATCH_RESPONSE]})

    request_id: str
    count: int
    decision_summary: dict[str, int] = Field(..., description="Number of cardholders per decision")
    predictions: list[BatchPredictionItem]
    latency_ms: float


class FeatureContribution(BaseModel):
    """Effect of one feature on the default probability."""

    feature: str
    value: float
    reference_value: float
    contribution: float = Field(
        ...,
        description="Change in default probability attributed to this feature. shap_permutation: SHAP value "
        "against the reference cardholder; reference_substitution: probability(cardholder) - "
        "probability(cardholder with this feature set to reference)",
    )
    direction: Literal["increases_risk", "decreases_risk", "neutral"]


class ExplainResponse(ScoreFields, _ServedModel):
    """Score plus local, model-based feature attributions for ``POST /api/v1/explain``."""

    model_config = ConfigDict(protected_namespaces=(), json_schema_extra={"examples": [ex.EXPLAIN_RESPONSE]})

    request_id: str
    method: Literal["shap_permutation", "reference_substitution"] = Field(
        ..., description="Attribution method (reference_substitution = degraded fallback)"
    )
    reference_probability: float = Field(..., description="Default probability of the reference (median) cardholder")
    contributions: list[FeatureContribution] = Field(..., description="Top features by absolute contribution")
    latency_ms: float


class ModelInfoResponse(BaseModel):
    """Metadata of the served model."""

    model_config = ConfigDict(protected_namespaces=(), json_schema_extra={"examples": [ex.MODEL_INFO_RESPONSE]})

    model_name: str
    model_alias: str
    model_version: str
    source: str
    uri: str
    run_id: str | None = None
    model_type: str
    loaded_at: datetime
    degraded: bool = Field(..., description="True when serving the local fallback instead of the registry champion")
    feature_names: list[str]
    thresholds: dict[str, float]


class ReloadResponse(BaseModel):
    """Outcome of ``POST /api/v1/model/reload``."""

    model_config = ConfigDict(protected_namespaces=(), json_schema_extra={"examples": [ex.RELOAD_RESPONSE]})

    status: Literal["reloaded", "unchanged_on_failure"]
    message: str
    previous_version: str | None
    model: ModelInfoResponse


class LivenessResponse(BaseModel):
    """Process liveness."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "alive", "version": "1.1.0"}]})

    status: Literal["alive"]
    version: str


class DependencyCheck(BaseModel):
    """State of one readiness dependency."""

    status: Literal["ok", "degraded", "down"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness: can this instance serve predictions, and at which quality level."""

    model_config = ConfigDict(json_schema_extra={"examples": [ex.READINESS_DEGRADED]})

    status: Literal["ready", "degraded", "not_ready"]
    reasons: list[str] = Field(default_factory=list)
    checks: dict[str, DependencyCheck]


class ErrorResponse(BaseModel):
    """Body of every non-2xx response."""

    model_config = ConfigDict(json_schema_extra={"examples": [ex.ERROR_VALIDATION]})

    code: str = Field(..., description="Stable machine-readable error code")
    message: str
    details: Any = None
    request_id: str | None = None
