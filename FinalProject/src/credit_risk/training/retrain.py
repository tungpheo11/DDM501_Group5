"""Continuous retraining: replay strategy, champion vs challenger gate, promotion, hot reload.

1. Combine baseline data with labeled feedback from the drifted stream (replay
   strategy against catastrophic forgetting) and validate it.
2. Refit the champion's algorithm with its tuned hyper-parameters
   (``models/model_spec.json`` written by ``make train``; config fallback otherwise).
3. Score champion and challenger on the **held-out** drifted feedback rows only
   (rows the challenger never trained on) and run the shared promotion gate
   (ROC-AUC non-inferiority + expected financial loss).
4. Register the challenger (``@challenger``) and move ``@champion`` when it passes.
5. Ask the serving API to hot-reload the champion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import joblib
import numpy as np
import pandas as pd
import requests
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from credit_risk.config import Settings, get_logger, get_settings
from credit_risk.data.manifest import build_manifest, load_manifest
from credit_risk.data.schema import ALL_FEATURES, REQUEST_ID_COLUMN, TARGET_COLUMN
from credit_risk.data.validation import validate_training_frame
from credit_risk.evaluation.metrics import classification_report_from_proba
from credit_risk.evaluation.model_validation import GateDecision, PromotionPolicy, compare_champion_challenger
from credit_risk.training.models import get_candidate
from credit_risk.training.pipeline import build_model_pipeline
from credit_risk.training.registry import get_alias_version, get_registry_client, log_model_run
from credit_risk.training.tracking import lineage_tags

logger = get_logger(__name__)

MODEL_SPEC_FILE = "model_spec.json"


@dataclass(frozen=True)
class RetrainResult:
    """Outcome of one retraining run (metrics are on the held-out drifted feedback rows)."""

    challenger: Pipeline
    challenger_metrics: dict[str, float]
    champion_metrics: dict[str, float]
    challenger_loss: float
    champion_loss: float
    promoted: bool
    gate: GateDecision | None = None
    registered_version: str | None = None
    candidate: str = "random_forest"
    params: dict[str, Any] = field(default_factory=dict)


def load_combined_training_data(
    settings: Settings | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Return ``(X, y, drifted_labeled)`` where X/y combine baseline and labeled feedback.

    Feedback rows are appended after the baseline rows, so ``X.index >= len(X) - len(drifted)``
    identifies them.
    """
    paths = (settings or get_settings()).paths
    df_baseline = pd.read_csv(paths.baseline_data)
    logger.info("Baseline data: %d samples (mean age %.1f)", len(df_baseline), df_baseline["AGE"].mean())

    df_features = pd.read_csv(paths.drifted_stream)
    df_feedback = pd.read_csv(paths.ground_truth)
    df_drifted = pd.merge(df_features, df_feedback, on=REQUEST_ID_COLUMN).drop(columns=[REQUEST_ID_COLUMN])
    logger.info("Ground-truth feedback: %d samples (mean age %.1f)", len(df_drifted), df_drifted["AGE"].mean())

    df_combined = validate_training_frame(
        pd.concat([df_baseline, df_drifted], ignore_index=True), name="baseline+feedback"
    )
    logger.info("Combined corpus: %d samples (mean age %.1f)", len(df_combined), df_combined["AGE"].mean())
    return df_combined[ALL_FEATURES], df_combined[TARGET_COLUMN], df_drifted


def load_champion_spec(settings: Settings | None = None) -> tuple[str, dict[str, Any], str]:
    """Algorithm and hyper-parameters to refit: ``models/model_spec.json`` or the config fallback.

    Returns:
        ``(candidate_name, params, source)``.
    """
    cfg = settings or get_settings()
    spec_path = cfg.paths.models_dir / MODEL_SPEC_FILE
    if spec_path.exists():
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        return get_candidate(spec["candidate"]).name, dict(spec["params"]), str(spec_path)
    fallback = cfg.training.challenger
    return get_candidate(fallback.model_type).name, dict(fallback.params), "configs/training.yaml"


def trigger_hot_reload(
    api_url: str,
    api_key: str = "",
    timeout: float = 10.0,
    expected_version: str | None = None,
) -> bool:
    """POST ``/api/v1/model/reload``; optionally verify the API now serves ``expected_version``."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        response = requests.post(f"{api_url.rstrip('/')}/api/v1/model/reload", headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Could not reach API for hot reload (%s).", exc)
        return False
    if response.status_code == 200:
        body = response.json()
        if expected_version is not None:
            model = body.get("model") or {}
            served_version = str(model.get("model_version"))
            if body.get("status") != "reloaded" or served_version != str(expected_version) or model.get("degraded"):
                logger.warning(
                    "Hot reload verification failed: expected v%s, status=%s served=v%s degraded=%s",
                    expected_version,
                    body.get("status"),
                    served_version,
                    model.get("degraded"),
                )
                return False
        logger.info("Hot reload triggered on API: %s", body)
        return True
    logger.warning("Hot reload returned HTTP %s", response.status_code)
    return False


def _load_current_champion(cfg: Settings) -> tuple[Any | None, str]:
    client = get_registry_client(cfg)
    if client is not None and get_alias_version(client, cfg.mlflow.model_name, cfg.mlflow.model_alias) is not None:
        import mlflow.sklearn

        uri = f"models:/{cfg.mlflow.model_name}@{cfg.mlflow.model_alias}"
        try:
            return mlflow.sklearn.load_model(uri), uri
        except Exception as exc:  # Fall back to the local artifact below.
            logger.warning("Could not load %s (%s); using the local champion artifact.", uri, exc)
    local = cfg.paths.models_dir / cfg.training.champion_artifact_name
    if local.exists():
        return joblib.load(local), str(local)
    return None, "none"


def run_retraining_pipeline(
    settings: Settings | None = None, reload_api: bool = True, promote: bool = True
) -> RetrainResult:
    """Execute the full champion/challenger retraining loop.

    Args:
        settings: Settings to use (defaults to the process-wide settings).
        reload_api: Ask the serving API to hot-reload after a promotion.
        promote: Move ``@champion`` when the gate passes. With ``False`` the challenger is
            only registered as ``@challenger`` and ``gate`` carries the decision, so an
            orchestrator (Airflow ``model_retrain``) can promote in a separate step.
    """
    cfg = settings or get_settings()
    cfg.paths.ensure_output_dirs()
    training = cfg.training
    spec = training.challenger

    x_all, y_all, df_drifted = load_combined_training_data(cfg)
    is_feedback = pd.Series(np.arange(len(x_all)) >= len(x_all) - len(df_drifted), index=x_all.index)
    x_train, x_val, y_train, y_val = train_test_split(
        x_all, y_all, test_size=training.test_size, random_state=training.random_state, stratify=y_all
    )
    eval_mask = is_feedback.loc[x_val.index].to_numpy()
    x_eval, y_eval = x_val[eval_mask], y_val[eval_mask]
    logger.info("Train %d | validation %d | held-out drifted feedback %d", len(x_train), len(x_val), len(x_eval))

    candidate, params, spec_source = load_champion_spec(cfg)
    logger.info("Challenger: %s with params from %s", candidate, spec_source)
    challenger = build_model_pipeline(params, random_state=training.random_state, model_name=candidate)
    challenger.fit(x_train, y_train)

    threshold, cost_fn, cost_fp = (
        training.decision_threshold,
        training.cost_false_negative,
        training.cost_false_positive,
    )
    val_metrics = classification_report_from_proba(
        y_val, challenger.predict_proba(x_val)[:, 1], threshold, cost_fn, cost_fp
    )
    challenger_metrics = classification_report_from_proba(
        y_eval, challenger.predict_proba(x_eval)[:, 1], threshold, cost_fn, cost_fp
    )

    champion, champion_source = _load_current_champion(cfg)
    champion_metrics: dict[str, float] = {}
    if champion is not None:
        champion_metrics = classification_report_from_proba(
            y_eval, champion.predict_proba(x_eval)[:, 1], threshold, cost_fn, cost_fp
        )
        logger.info(
            "Champion   | ROC-AUC: %.4f | F1: %.4f | Loss: %.0f",
            champion_metrics["roc_auc"],
            champion_metrics["f1_score"],
            champion_metrics["financial_loss"],
        )
    logger.info(
        "Challenger | ROC-AUC: %.4f | F1: %.4f | Loss: %.0f",
        challenger_metrics["roc_auc"],
        challenger_metrics["f1_score"],
        challenger_metrics["financial_loss"],
    )

    promotion = training.promotion
    gate = compare_champion_challenger(
        challenger_metrics,
        champion_metrics or None,
        PromotionPolicy(promotion.min_roc_auc, promotion.max_roc_auc_drop, promotion.min_loss_improvement),
    )
    logger.info("Gate vs %s: %s | %s", champion_source, "PROMOTE" if gate.promote else "KEEP", gate.reasons)

    manifest_path = cfg.paths.data_manifest
    manifest = load_manifest(manifest_path) if manifest_path.exists() else build_manifest(cfg.paths.data_dir)
    result = log_model_run(
        challenger,
        run_name=spec.run_name,
        params={
            "candidate": candidate,
            **params,
            "strategy": spec.strategy,
            "spec_source": spec_source,
            "train_samples": len(x_train),
            "eval_samples": len(x_eval),
        },
        metrics={
            **{f"val_{k}": float(v) for k, v in val_metrics.items()},
            **{f"drifted_holdout_{k}": float(v) for k, v in challenger_metrics.items()},
            **{f"champion_drifted_holdout_{k}": float(v) for k, v in champion_metrics.items()},
        },
        sample_input=x_val,
        register=True,
        promote=promote and gate.promote,
        settings=cfg,
        tags={
            "run_type": "retrain",
            "gate_decision": "promote" if gate.promote else "reject",
            "gate_reasons": " | ".join(gate.reasons)[:4900],
            **lineage_tags(
                manifest,
                ["reference/train_baseline.csv", "processed/stream_drifted.csv", "processed/ground_truth_feedback.csv"],
            ),
        },
    )

    challenger_path = cfg.paths.models_dir / spec.artifact_name
    joblib.dump(challenger, challenger_path)
    logger.info("Challenger saved locally to %s", challenger_path)
    promoted = promote and gate.promote
    if promoted:
        joblib.dump(challenger, cfg.paths.models_dir / training.champion_artifact_name)
        logger.info("Local champion artifact replaced by the promoted challenger.")

    if reload_api and promoted:
        trigger_hot_reload(cfg.serving.api_url, cfg.serving.client_api_key)

    return RetrainResult(
        challenger=challenger,
        challenger_metrics=challenger_metrics,
        champion_metrics=champion_metrics,
        challenger_loss=challenger_metrics["financial_loss"],
        champion_loss=champion_metrics.get("financial_loss", 0.0),
        promoted=promoted,
        gate=gate,
        registered_version=result.registered_version if result else None,
        candidate=candidate,
        params=params,
    )
