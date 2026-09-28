"""Hyper-parameter optimisation with Optuna and stratified K-fold cross-validation.

Tracking-agnostic: MLflow logging is injected through ``trial_callback`` so the
search can be unit-tested (and reused by Airflow) without a tracking server.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from credit_risk.config import get_logger
from credit_risk.evaluation.business_cost import cost_optimal_threshold
from credit_risk.evaluation.metrics import classification_report_from_proba
from credit_risk.training.models import class_balance_params, get_candidate
from credit_risk.training.pipeline import build_model_pipeline

logger = get_logger(__name__)

TrialCallback = Callable[[optuna.Study, optuna.trial.FrozenTrial], None]
SUPPORTED_METRICS = ("roc_auc", "pr_auc")


@dataclass(frozen=True)
class CostSettings:
    """Decision threshold and cost matrix used for business metrics."""

    threshold: float = 0.5
    cost_fn: float = 10.0
    cost_fp: float = 1.0


@dataclass
class CrossValidationResult:
    """Fold scores and out-of-fold (OOF) predictions of one parameter set."""

    fold_roc_auc: list[float]
    fold_pr_auc: list[float]
    oof_proba: np.ndarray
    metrics: dict[str, float]


@dataclass
class TuningResult:
    """Best parameters of one candidate and the evidence behind them."""

    candidate: str
    best_params: dict[str, Any]
    best_value: float
    best_trial: int
    cv: CrossValidationResult
    study: optuna.Study
    n_trials: int
    n_pruned: int
    duration_seconds: float
    fixed_params: dict[str, Any] = field(default_factory=dict)


def cross_validate_pipeline(
    model_name: str,
    params: dict[str, Any],
    features: pd.DataFrame,
    target: pd.Series,
    *,
    cv_folds: int = 5,
    random_state: int = 42,
    costs: CostSettings | None = None,
    on_fold: Callable[[int, float], None] | None = None,
) -> CrossValidationResult:
    """Stratified K-fold CV of the full pipeline; returns fold AUCs and OOF-based metrics.

    ``on_fold(fold_index, running_mean_roc_auc)`` is called after every fold (used for pruning).
    """
    cost = costs or CostSettings()
    labels = target.to_numpy()
    splitter = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    oof = np.zeros(len(target), dtype=float)
    fold_roc: list[float] = []
    fold_pr: list[float] = []

    for fold, (train_idx, val_idx) in enumerate(splitter.split(features, labels)):
        pipeline = build_model_pipeline(params, random_state=random_state, model_name=model_name)
        pipeline.fit(features.iloc[train_idx], labels[train_idx])
        proba = pipeline.predict_proba(features.iloc[val_idx])[:, 1]
        oof[val_idx] = proba
        fold_roc.append(float(roc_auc_score(labels[val_idx], proba)))
        fold_pr.append(float(average_precision_score(labels[val_idx], proba)))
        if on_fold is not None:
            on_fold(fold, float(np.mean(fold_roc)))

    oof_report = classification_report_from_proba(labels, oof, cost.threshold, cost.cost_fn, cost.cost_fp)
    best_threshold, _ = cost_optimal_threshold(labels, oof, cost.cost_fn, cost.cost_fp)
    metrics = {
        "roc_auc_mean": float(np.mean(fold_roc)),
        "roc_auc_std": float(np.std(fold_roc)),
        "pr_auc_mean": float(np.mean(fold_pr)),
        "pr_auc_std": float(np.std(fold_pr)),
        "oof_f1_score": oof_report["f1_score"],
        "oof_recall": oof_report["recall"],
        "oof_precision": oof_report["precision"],
        "oof_expected_loss": oof_report["expected_loss"],
        "oof_brier": oof_report["brier"],
        "cost_optimal_threshold": best_threshold,
    }
    return CrossValidationResult(fold_roc_auc=fold_roc, fold_pr_auc=fold_pr, oof_proba=oof, metrics=metrics)


def tune_candidate(
    model_name: str,
    features: pd.DataFrame,
    target: pd.Series,
    *,
    n_trials: int = 20,
    cv_folds: int = 5,
    random_state: int = 42,
    costs: CostSettings | None = None,
    metric: str = "roc_auc",
    timeout_seconds: float | None = None,
    trial_callback: TrialCallback | None = None,
) -> TuningResult:
    """Search ``model_name``'s space with TPE (seeded) + median pruning on CV ``metric``.

    Raises:
        ValueError: for an unsupported ``metric``.
    """
    if metric not in SUPPORTED_METRICS:
        raise ValueError(f"Unsupported tuning metric '{metric}'. Use one of {SUPPORTED_METRICS}.")
    candidate = get_candidate(model_name)
    fixed = class_balance_params(candidate.name, target.to_numpy())
    results: dict[int, CrossValidationResult] = {}

    def objective(trial: optuna.Trial) -> float:
        params = {**candidate.sample_params(trial), **fixed}

        def report(fold: int, running_mean: float) -> None:
            trial.report(running_mean, fold)
            if trial.should_prune():
                raise optuna.TrialPruned()

        result = cross_validate_pipeline(
            candidate.name,
            params,
            features,
            target,
            cv_folds=cv_folds,
            random_state=random_state,
            costs=costs,
            on_fold=report if metric == "roc_auc" else None,
        )
        results[trial.number] = result
        for key, value in result.metrics.items():
            trial.set_user_attr(key, value)
        return result.metrics[f"{metric}_mean"]

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        study_name=f"{candidate.name}-hpo",
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=random_state),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=1),
    )
    started = time.perf_counter()
    study.optimize(
        objective,
        n_trials=n_trials,
        timeout=timeout_seconds,
        callbacks=[trial_callback] if trial_callback else None,
        gc_after_trial=True,
    )
    duration = time.perf_counter() - started

    best = study.best_trial
    assert best.value is not None
    n_pruned = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED)
    logger.info(
        "%s: best CV %s=%.4f (trial %d) after %d trials (%d pruned) in %.1fs",
        candidate.display_name,
        metric,
        best.value,
        best.number,
        len(study.trials),
        n_pruned,
        duration,
    )
    return TuningResult(
        candidate=candidate.name,
        best_params={**best.params, **fixed},
        best_value=float(best.value),
        best_trial=best.number,
        cv=results[best.number],
        study=study,
        n_trials=len(study.trials),
        n_pruned=n_pruned,
        duration_seconds=duration,
        fixed_params=fixed,
    )
