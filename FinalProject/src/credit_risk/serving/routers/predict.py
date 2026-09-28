"""``/api/v1`` scoring routes: single, batch and explained predictions."""

from __future__ import annotations

import time
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Body, Depends

from credit_risk.config import Settings, get_logger
from credit_risk.serving import openapi_examples as ex
from credit_risk.serving.dependencies import get_request_id, get_scoring_service, get_settings_dep, require_model
from credit_risk.serving.errors import ApiError
from credit_risk.serving.model_loader import LoadedModel
from credit_risk.serving.schemas import (
    BatchPredictionItem,
    BatchPredictionResponse,
    BatchPredictRequest,
    CreditPredictRequest,
    ExplainResponse,
    FeatureContribution,
    PredictionResponse,
)
from credit_risk.serving.scoring import ScoringService

router = APIRouter(prefix="/api/v1", tags=["prediction"])
logger = get_logger(__name__)

_SCORING_ERRORS = ex.error_responses(401, 403, 422, 500, 503)


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


@router.post(
    "/predict",
    response_model=PredictionResponse,
    summary="Score one applicant",
    description="Returns default probability, APPROVE/REVIEW/DECLINE decision, credit score, tier, "
    "recommended limit, rule-based risk factors and policy guardrails. The request is logged for drift analysis.",
    responses=_SCORING_ERRORS,
)
def predict(
    payload: Annotated[CreditPredictRequest, Body(openapi_examples=ex.PREDICT_REQUEST_EXAMPLES)],
    loaded: Annotated[LoadedModel, Depends(require_model)],
    service: Annotated[ScoringService, Depends(get_scoring_service)],
    request_id: Annotated[str, Depends(get_request_id)],
) -> PredictionResponse:
    start = time.perf_counter()
    result = service.score(loaded, [payload.model_dump()])[0]
    latency_ms = _elapsed_ms(start)
    service.record([result], [request_id], loaded, latency_ms)
    logger.info(
        "Prediction served",
        extra={
            "event": "prediction",
            "decision": result.outcome.decision,
            "model_version": loaded.version,
            "latency_ms": latency_ms,
        },
    )
    return PredictionResponse(
        request_id=request_id,
        model_version=loaded.version,
        served_by=loaded.source,
        latency_ms=latency_ms,
        **result.as_fields(),
    )


@router.post(
    "/predict/batch",
    response_model=BatchPredictionResponse,
    summary="Score several applicants",
    description="Vectorized scoring of up to `batch_max_size` applicants (configs/serving.yaml, default 500). "
    "Results keep request order; each item gets its own `<request_id>-<index>` id in the inference log.",
    responses=ex.error_responses(401, 403, 413, 422, 500, 503),
)
def predict_batch(
    payload: Annotated[BatchPredictRequest, Body(openapi_examples=ex.BATCH_REQUEST_EXAMPLES)],
    loaded: Annotated[LoadedModel, Depends(require_model)],
    service: Annotated[ScoringService, Depends(get_scoring_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    request_id: Annotated[str, Depends(get_request_id)],
) -> BatchPredictionResponse:
    max_size = settings.serving.batch_max_size
    received = len(payload.applicants)
    if received > max_size:
        raise ApiError(
            413,
            "BATCH_TOO_LARGE",
            f"Batch contains {received} applicants; the maximum is {max_size}.",
            {"max_size": max_size, "received": received},
        )

    start = time.perf_counter()
    results = service.score(loaded, [applicant.model_dump() for applicant in payload.applicants])
    latency_ms = _elapsed_ms(start)
    item_ids = [f"{request_id}-{index}" for index in range(received)]
    service.record(results, item_ids, loaded, latency_ms)

    summary = Counter(result.outcome.decision for result in results)
    decision_summary = {decision: summary.get(decision, 0) for decision in ("APPROVE", "REVIEW", "DECLINE")}
    logger.info(
        "Batch prediction served",
        extra={"event": "batch_prediction", "count": received, "decisions": decision_summary, "latency_ms": latency_ms},
    )
    return BatchPredictionResponse(
        request_id=request_id,
        count=received,
        decision_summary=decision_summary,
        predictions=[
            BatchPredictionItem(index=index, request_id=item_id, **result.as_fields())
            for index, (item_id, result) in enumerate(zip(item_ids, results, strict=True))
        ],
        model_version=loaded.version,
        served_by=loaded.source,
        latency_ms=latency_ms,
    )


@router.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Score one applicant and explain the score",
    description="Adds local, model-based attributions (top-k by magnitude). Default method `shap_permutation`: "
    "SHAP values against the median training applicant, so contributions sum to "
    "`default_probability - reference_probability`, and `top_risk_factors` is derived from them. "
    "If SHAP fails the endpoint degrades to `reference_substitution` (each feature replaced by the "
    "reference value). Explanations are not written to the inference log.",
    responses=_SCORING_ERRORS,
)
def explain(
    payload: Annotated[CreditPredictRequest, Body(openapi_examples=ex.PREDICT_REQUEST_EXAMPLES)],
    loaded: Annotated[LoadedModel, Depends(require_model)],
    service: Annotated[ScoringService, Depends(get_scoring_service)],
    request_id: Annotated[str, Depends(get_request_id)],
) -> ExplainResponse:
    start = time.perf_counter()
    result, reference_probability, contributions, method = service.explain(loaded, payload.model_dump())
    latency_ms = _elapsed_ms(start)
    logger.info(
        "Explanation served",
        extra={
            "event": "explanation",
            "method": method,
            "decision": result.outcome.decision,
            "latency_ms": latency_ms,
        },
    )
    return ExplainResponse(
        request_id=request_id,
        method=method,
        reference_probability=reference_probability,
        contributions=[
            FeatureContribution(
                feature=item.feature,
                value=item.value,
                reference_value=item.reference_value,
                contribution=item.contribution,
                direction=item.direction,
            )
            for item in contributions
        ],
        model_version=loaded.version,
        served_by=loaded.source,
        latency_ms=latency_ms,
        **result.as_fields(),
    )
