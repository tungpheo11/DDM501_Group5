"""End-to-end training: validate -> tune candidates -> select -> gate -> register -> report.

``make train`` calls :func:`run_training_pipeline`. Steps:

1. Validate ``reference/train_baseline.csv`` and the gate set (pandera) and record the
   data snapshot (manifest fingerprint + per-file SHA-256) for lineage.
2. Stratified holdout split; Optuna HPO with stratified K-fold CV for every candidate.
   Each candidate is a parent MLflow run; each Optuna trial is a nested run.
3. Refit each candidate's best parameters on the full training split, evaluate on the
   holdout and on ``processed/stream_normal.csv`` (the gate set, never used to train).
4. Select the best candidate by CV metric, register it, and run the champion/challenger
   gate against the current ``@champion`` on the gate set; promote when it passes.
5. Write ``reports/model_comparison.{json,md}``, figures and sync the README table.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from credit_risk.config import Settings, get_logger, get_settings
from credit_risk.data.manifest import build_manifest, load_manifest, manifest_fingerprint, sha256_of
from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN
from credit_risk.data.validation import build_engineered_schema, validate_frame, validate_training_frame
from credit_risk.evaluation.metrics import classification_report_from_proba
from credit_risk.evaluation.model_validation import GateDecision, PromotionPolicy, compare_champion_challenger
from credit_risk.evaluation.plots import (
    feature_importances,
    plot_confusion_matrix,
    plot_feature_importance,
    plot_pr_curves,
    plot_roc_curves,
)
from credit_risk.features.feature_engineering import ENGINEERED_FEATURES, engineer_features
from credit_risk.training import reporting
from credit_risk.training.models import get_candidate
from credit_risk.training.pipeline import build_model_pipeline
from credit_risk.training.registry import (
    CHALLENGER_ALIAS,
    get_alias_version,
    get_registry_client,
    log_sklearn_model,
    promote_model_version,
)
from credit_risk.training.tracking import init_mlflow, lineage_tags, log_json, log_lineage
from credit_risk.training.tuning import CostSettings, TuningResult, tune_candidate

logger = get_logger(__name__)

MODEL_SPEC_FILE = "model_spec.json"


@dataclass
class CandidateOutcome:
    """Everything known about one tuned candidate after refitting on the training split."""

    name: str
    display_name: str
    tuning: TuningResult
    pipeline: Pipeline
    holdout_metrics: dict[str, float]
    gate_metrics: dict[str, float]
    holdout_proba: np.ndarray
    run_id: str | None = None
    model_uri: str | None = None


@dataclass
class TrainingOutcome:
    """Result of :func:`run_training_pipeline`."""

    session_id: str
    candidates: list[CandidateOutcome]
    selected: CandidateOutcome
    gate: GateDecision
    report: dict[str, Any]
    tracking_uri: str | None
    registered_version: str | None = None
    champion_version: str | None = None
    report_paths: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class _DataSnapshot:
    train: pd.DataFrame
    gate: pd.DataFrame
    manifest: dict[str, Any]
    used_files: list[str]
    verified: bool


def _relative_to_data(path: Path, data_dir: Path) -> str:
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _load_snapshot(cfg: Settings) -> _DataSnapshot:
    """Validate the training and gate datasets and reconcile them with the manifest."""
    paths = cfg.paths
    train_rel = _relative_to_data(paths.baseline_data, paths.data_dir)
    gate_rel = _relative_to_data(paths.normal_stream, paths.data_dir)
    train = validate_training_frame(pd.read_csv(paths.baseline_data), name=train_rel)
    gate = validate_training_frame(pd.read_csv(paths.normal_stream), name=gate_rel)
    logger.info("Validated %s (%d rows) and %s (%d rows)", train_rel, len(train), gate_rel, len(gate))

    manifest = load_manifest(paths.data_manifest) if paths.data_manifest.exists() else build_manifest(paths.data_dir)
    recorded = {entry["path"]: entry for entry in manifest.get("files", [])}
    verified = True
    for relative, path in ((train_rel, paths.baseline_data), (gate_rel, paths.normal_stream)):
        actual = sha256_of(path)
        if recorded.get(relative, {}).get("sha256") != actual:
            verified = False
            logger.warning("%s does not match data/manifest.json; run `make manifest` to re-version it.", relative)
            recorded[relative] = {"path": relative, "sha256": actual, "rows": len(pd.read_csv(path))}
    files = list(recorded.values())
    snapshot_manifest = {**manifest, "files": files, "fingerprint": manifest_fingerprint(files)}
    return _DataSnapshot(train, gate, snapshot_manifest, [train_rel, gate_rel], verified)


def _prefixed(prefix: str, metrics: dict[str, float]) -> dict[str, float]:
    return {f"{prefix}_{key}": float(value) for key, value in metrics.items()}


def _trial_logger(candidate: str, session_tags: dict[str, str]) -> Any:
    """Optuna callback logging each finished trial as a nested MLflow run."""
    import mlflow

    def _log(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        with mlflow.start_run(run_name=f"{candidate}-trial-{trial.number:03d}", nested=True):
            trial_tags = {"candidate": candidate, "run_type": "hpo_trial", "state": trial.state.name}
            mlflow.set_tags({**session_tags, **trial_tags})
            mlflow.log_params(trial.params)
            numeric = {k: float(v) for k, v in trial.user_attrs.items() if isinstance(v, int | float)}
            if trial.value is not None:
                numeric["objective"] = float(trial.value)
            for step, value in trial.intermediate_values.items():
                mlflow.log_metric("running_cv_roc_auc", float(value), step=step)
            mlflow.log_metrics({f"cv_{k}" if k != "objective" else k: v for k, v in numeric.items()})

    return _log


def _log_candidate_artifacts(outcome: CandidateOutcome, y_holdout: np.ndarray, threshold: float) -> None:
    import mlflow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        label = outcome.display_name
        preds = (outcome.holdout_proba >= threshold).astype(int)
        plot_confusion_matrix(y_holdout, preds, root / "plots/confusion_matrix.png", f"{label} — holdout")
        plot_roc_curves({label: (y_holdout, outcome.holdout_proba)}, root / "plots/roc_curve.png", "ROC — holdout")
        plot_pr_curves({label: (y_holdout, outcome.holdout_proba)}, root / "plots/pr_curve.png", "PR — holdout")
        importances = feature_importances(outcome.pipeline)
        if not importances.empty:
            importances.to_csv(root / "plots/feature_importance.csv", index=False)
            plot_feature_importance(importances, root / "plots/feature_importance.png", f"{label} — importance")
        trials = outcome.tuning.study.trials_dataframe()
        (root / "tuning").mkdir(parents=True, exist_ok=True)
        trials.to_csv(root / "tuning/trials.csv", index=False)
        mlflow.log_artifacts(str(root))


def _tune_and_fit(
    name: str,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_holdout: pd.DataFrame,
    y_holdout: pd.Series,
    gate: pd.DataFrame,
    cfg: Settings,
    costs: CostSettings,
    n_trials: int,
    trial_callback: Any,
) -> CandidateOutcome:
    training = cfg.training
    candidate = get_candidate(name)
    tuning = tune_candidate(
        candidate.name,
        x_train,
        y_train,
        n_trials=n_trials,
        cv_folds=training.cv_folds,
        random_state=training.random_state,
        costs=costs,
        metric=training.selection_metric,
        timeout_seconds=training.tuning_timeout_seconds,
        trial_callback=trial_callback,
    )
    pipeline = build_model_pipeline(tuning.best_params, random_state=training.random_state, model_name=candidate.name)
    pipeline.fit(x_train, y_train)

    holdout_proba = pipeline.predict_proba(x_holdout)[:, 1]
    holdout = classification_report_from_proba(y_holdout, holdout_proba, costs.threshold, costs.cost_fn, costs.cost_fp)
    gate_proba = pipeline.predict_proba(gate[ALL_FEATURES])[:, 1]
    gate_metrics = classification_report_from_proba(
        gate[TARGET_COLUMN], gate_proba, costs.threshold, costs.cost_fn, costs.cost_fp
    )
    logger.info(
        "%s | holdout ROC-AUC %.4f PR-AUC %.4f F1 %.4f expected loss %.4f | normal-stream ROC-AUC %.4f",
        candidate.display_name,
        holdout["roc_auc"],
        holdout["pr_auc"],
        holdout["f1_score"],
        holdout["expected_loss"],
        gate_metrics["roc_auc"],
    )
    return CandidateOutcome(
        name=candidate.name,
        display_name=candidate.display_name,
        tuning=tuning,
        pipeline=pipeline,
        holdout_metrics=holdout,
        gate_metrics=gate_metrics,
        holdout_proba=holdout_proba,
    )


def _current_champion(cfg: Settings, client: Any | None) -> tuple[Any | None, str | None, str]:
    """Current champion model, its registry version (if any) and a human-readable source."""
    if client is not None:
        version = get_alias_version(client, cfg.mlflow.model_name, cfg.mlflow.model_alias)
        if version is not None:
            import mlflow.sklearn

            uri = f"models:/{cfg.mlflow.model_name}@{cfg.mlflow.model_alias}"
            try:
                return mlflow.sklearn.load_model(uri), version, uri
            except Exception as exc:  # A broken champion artifact must not block training.
                logger.warning("Could not load current champion %s (%s); treating as absent.", uri, exc)
                return None, version, uri
        return None, None, "registry (no champion yet)"
    local = cfg.paths.models_dir / cfg.training.champion_artifact_name
    if local.exists():
        try:
            return joblib.load(local), None, str(local)
        except Exception as exc:  # Incompatible pickle from an older library version.
            logger.warning("Could not load local champion %s (%s); treating as absent.", local, exc)
    return None, None, "none"


def _save_local_champion(cfg: Settings, outcome: CandidateOutcome, report_meta: dict[str, Any]) -> Path:
    models_dir = cfg.paths.models_dir
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact = models_dir / cfg.training.champion_artifact_name
    joblib.dump(outcome.pipeline, artifact)
    spec = {
        "candidate": outcome.name,
        "params": outcome.tuning.best_params,
        "decision_threshold": cfg.training.decision_threshold,
        **report_meta,
    }
    (models_dir / MODEL_SPEC_FILE).write_text(json.dumps(spec, indent=2, default=str) + "\n", encoding="utf-8")
    logger.info("Champion pipeline saved to %s", artifact)
    return artifact


def _round(metrics: dict[str, float]) -> dict[str, float]:
    return {key: (round(value, 6) if isinstance(value, float) else value) for key, value in metrics.items()}


def _write_figures(
    reports_dir: Path, outcomes: list[CandidateOutcome], selected: CandidateOutcome, y_holdout: np.ndarray, t: float
) -> None:
    figures = reports_dir / "figures"
    curves = {o.display_name: (y_holdout, o.holdout_proba) for o in outcomes}
    plot_roc_curves(curves, figures / "roc_comparison.png", "ROC — holdout (all candidates)")
    plot_pr_curves(curves, figures / "pr_comparison.png", "Precision-Recall — holdout (all candidates)")
    plot_confusion_matrix(
        y_holdout,
        (selected.holdout_proba >= t).astype(int),
        figures / "confusion_matrix_selected.png",
        f"{selected.display_name} — holdout",
    )
    importances = feature_importances(selected.pipeline)
    if not importances.empty:
        plot_feature_importance(
            importances, figures / "feature_importance_selected.png", f"{selected.display_name} — importance"
        )


def run_training_pipeline(
    settings: Settings | None = None,
    *,
    n_trials: int | None = None,
    candidates: list[str] | None = None,
    register: bool = True,
    sync_readme: bool = True,
) -> TrainingOutcome:
    """Run the full training workflow described in the module docstring.

    Args:
        settings: configuration; defaults to the cached process settings.
        n_trials: Optuna trials per candidate (overrides ``configs/training.yaml``).
        candidates: subset of algorithms to train (default: ``training.candidates``).
        register: register the selected model and run the promotion gate in MLflow.
        sync_readme: refresh the README results block between its markers.

    Raises:
        credit_risk.data.validation.DataValidationError: when an input dataset is invalid.
    """
    cfg = settings or get_settings()
    cfg.paths.ensure_output_dirs()
    training = cfg.training
    costs = CostSettings(training.decision_threshold, training.cost_false_negative, training.cost_false_positive)
    trials = n_trials or training.n_trials
    names = candidates or list(training.candidates)
    session_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    snapshot = _load_snapshot(cfg)
    features, target = snapshot.train[ALL_FEATURES], snapshot.train[TARGET_COLUMN]
    x_train, x_holdout, y_train, y_holdout = train_test_split(
        features, target, test_size=training.test_size, random_state=training.random_state, stratify=target
    )
    validate_frame(engineer_features(x_train), build_engineered_schema(ENGINEERED_FEATURES, "engineered_features"))
    logger.info("Session %s | train %d | holdout %d | candidates %s", session_id, len(x_train), len(x_holdout), names)

    tracking_uri = init_mlflow(cfg)
    session_tags = {
        "training_session": session_id,
        **lineage_tags(snapshot.manifest, snapshot.used_files),
        "data_manifest_verified": str(snapshot.verified).lower(),
    }
    run_params = {
        "cv_folds": training.cv_folds,
        "n_trials": trials,
        "random_state": training.random_state,
        "decision_threshold": training.decision_threshold,
        "cost_false_negative": training.cost_false_negative,
        "cost_false_positive": training.cost_false_positive,
        "train_rows": len(x_train),
        "holdout_rows": len(x_holdout),
        "n_engineered_features": len(ENGINEERED_FEATURES),
    }

    outcomes: list[CandidateOutcome] = []
    for name in names:
        if tracking_uri is None:
            outcomes.append(
                _tune_and_fit(name, x_train, y_train, x_holdout, y_holdout, snapshot.gate, cfg, costs, trials, None)
            )
            continue
        import mlflow

        with mlflow.start_run(run_name=f"{name}-{session_id}") as run:
            mlflow.set_tags({**session_tags, "candidate": name, "run_type": "candidate"})
            outcome = _tune_and_fit(
                name,
                x_train,
                y_train,
                x_holdout,
                y_holdout,
                snapshot.gate,
                cfg,
                costs,
                trials,
                _trial_logger(name, session_tags),
            )
            mlflow.log_params({**run_params, "candidate": name, **outcome.tuning.best_params})
            mlflow.log_metrics(
                {
                    **_prefixed("cv", outcome.tuning.cv.metrics),
                    **_prefixed("holdout", outcome.holdout_metrics),
                    **_prefixed("normal_stream", outcome.gate_metrics),
                    "tuning_seconds": outcome.tuning.duration_seconds,
                    "n_trials_pruned": float(outcome.tuning.n_pruned),
                }
            )
            log_lineage(
                snapshot.manifest,
                {
                    "train_split": (x_train.assign(**{TARGET_COLUMN: y_train}), cfg.paths.baseline_data, "training"),
                    "holdout_split": (
                        x_holdout.assign(**{TARGET_COLUMN: y_holdout}),
                        cfg.paths.baseline_data,
                        "validation",
                    ),
                    "normal_stream": (snapshot.gate, cfg.paths.normal_stream, "gate"),
                },
            )
            _log_candidate_artifacts(outcome, y_holdout.to_numpy(), costs.threshold)
            info = log_sklearn_model(outcome.pipeline, x_train, register=False, settings=cfg)
            outcome.run_id, outcome.model_uri = run.info.run_id, info["model_uri"]
        outcomes.append(outcome)

    metric_key = f"{training.selection_metric}_mean"
    selected = max(outcomes, key=lambda o: (o.tuning.cv.metrics[metric_key], o.holdout_metrics["roc_auc"]))
    logger.info("Selected challenger: %s (CV %s %.4f)", selected.display_name, metric_key, selected.tuning.best_value)

    client = get_registry_client(cfg) if (register and tracking_uri) else None
    champion_model, previous_champion_version, champion_source = _current_champion(cfg, client)
    champion_version = previous_champion_version
    champion_metrics = None
    if champion_model is not None:
        gate_proba = champion_model.predict_proba(snapshot.gate[ALL_FEATURES])[:, 1]
        champion_metrics = classification_report_from_proba(
            snapshot.gate[TARGET_COLUMN], gate_proba, costs.threshold, costs.cost_fn, costs.cost_fp
        )
    policy = PromotionPolicy(
        training.promotion.min_roc_auc, training.promotion.max_roc_auc_drop, training.promotion.min_loss_improvement
    )
    decision = compare_champion_challenger(selected.gate_metrics, champion_metrics, policy)
    logger.info("Gate vs %s: %s | %s", champion_source, "PROMOTE" if decision.promote else "KEEP", decision.reasons)

    registered_version = None
    if client is not None and selected.model_uri is not None:
        import mlflow

        version = mlflow.register_model(selected.model_uri, cfg.mlflow.model_name).version
        registered_version = str(version)
        for key, value in {
            "candidate": selected.name,
            "training_session": session_id,
            "data_version": session_tags["data_version"],
            "gate_decision": "promote" if decision.promote else "reject",
            "gate_reasons": " | ".join(decision.reasons)[:4900],
            "normal_stream_roc_auc": f"{selected.gate_metrics['roc_auc']:.6f}",
            "normal_stream_expected_loss": f"{selected.gate_metrics['expected_loss']:.6f}",
            "source_run_id": selected.run_id or "",
        }.items():
            client.set_model_version_tag(cfg.mlflow.model_name, registered_version, key, value)
        client.set_registered_model_alias(cfg.mlflow.model_name, CHALLENGER_ALIAS, registered_version)
        if decision.promote:
            promote_model_version(registered_version, settings=cfg, client=client, reason=f"gate: {session_id}")
            champion_version = registered_version
        with mlflow.start_run(run_id=selected.run_id):
            log_json(decision.to_dict(), "gate/decision.json")
            mlflow.set_tags({"gate_decision": "promote" if decision.promote else "reject", "selected": "true"})

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "session_id": session_id,
        "selected_model": selected.name,
        "config": {
            **run_params,
            "test_size": training.test_size,
            "metric": training.selection_metric,
            "candidates": names,
        },
        "data": {
            "train_file": snapshot.used_files[0],
            "gate_file": snapshot.used_files[1],
            "train_rows": len(x_train),
            "holdout_rows": len(x_holdout),
            "gate_rows": len(snapshot.gate),
            "data_version": session_tags["data_version"],
            "manifest_verified": snapshot.verified,
        },
        "models": [
            {
                "name": o.name,
                "display_name": o.display_name,
                "best_params": o.tuning.best_params,
                "cv": _round(o.tuning.cv.metrics),
                "cv_fold_roc_auc": [round(v, 6) for v in o.tuning.cv.fold_roc_auc],
                "holdout": _round(o.holdout_metrics),
                "normal_stream": _round(o.gate_metrics),
                "tuning": {
                    "n_trials": o.tuning.n_trials,
                    "n_pruned": o.tuning.n_pruned,
                    "best_trial": o.tuning.best_trial,
                    "duration_seconds": round(o.tuning.duration_seconds, 2),
                },
                "mlflow_run_id": o.run_id,
            }
            for o in outcomes
        ],
        "gate": {
            **decision.to_dict(),
            "champion_source": champion_source,
            "champion_version_before": previous_champion_version,
            "evaluation_set": snapshot.used_files[1],
        },
        "registry": {
            "tracking_uri": tracking_uri,
            "model_name": cfg.mlflow.model_name,
            "registered_version": registered_version,
            "champion_version": champion_version,
        },
    }

    if decision.promote:
        _save_local_champion(cfg, selected, {"training_session": session_id, "registered_version": registered_version})

    reports_dir = cfg.paths.reports_dir
    _write_figures(reports_dir, outcomes, selected, y_holdout.to_numpy(), costs.threshold)
    report_paths = {
        "json": reporting.write_json_report(report, reports_dir / "model_comparison.json"),
        "markdown": reporting.write_markdown_report(report, reports_dir / "model_comparison.md"),
    }
    if sync_readme and reporting.sync_readme(report, cfg.paths.project_root / "README.md"):
        logger.info("README results table refreshed from %s", report_paths["json"])

    return TrainingOutcome(
        session_id=session_id,
        candidates=outcomes,
        selected=selected,
        gate=decision,
        report=report,
        tracking_uri=tracking_uri,
        registered_version=registered_version,
        champion_version=champion_version,
        report_paths=report_paths,
    )
