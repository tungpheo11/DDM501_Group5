"""Candidate algorithms and their Optuna search spaces.

Every candidate handles the ~22% default rate with class weighting so that the
0.5 probability cut-off used by ``model.predict`` stays meaningful.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import optuna
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

ParamSampler = Callable[[optuna.Trial], dict[str, Any]]
EstimatorFactory = Callable[[dict[str, Any], int], Any]


@dataclass(frozen=True)
class CandidateModel:
    """One algorithm: how to build it, how to sample it and its safe defaults."""

    name: str
    display_name: str
    factory: EstimatorFactory
    sample_params: ParamSampler
    default_params: dict[str, Any]

    def build(self, params: dict[str, Any], random_state: int) -> Any:
        """Instantiate the estimator with ``params`` on top of :attr:`default_params`."""
        return self.factory({**self.default_params, **params}, random_state)


def _positive_weight(target: np.ndarray | None) -> float:
    if target is None or len(target) == 0:
        return 1.0
    positives = float(np.sum(target))
    return (len(target) - positives) / positives if positives else 1.0


def class_balance_params(name: str, target: np.ndarray | None) -> dict[str, Any]:
    """Data-dependent parameters fixed for a candidate (not tuned): XGBoost ``scale_pos_weight``."""
    if name == "xgboost":
        return {"scale_pos_weight": round(_positive_weight(target), 4)}
    return {}


def _logistic_regression(params: dict[str, Any], random_state: int) -> LogisticRegression:
    return LogisticRegression(random_state=random_state, **params)


def _sample_logistic_regression(trial: optuna.Trial) -> dict[str, Any]:
    return {"C": trial.suggest_float("C", 1e-3, 10.0, log=True)}


def _random_forest(params: dict[str, Any], random_state: int) -> RandomForestClassifier:
    return RandomForestClassifier(random_state=random_state, **params)


def _sample_random_forest(trial: optuna.Trial) -> dict[str, Any]:
    return {
        "n_estimators": trial.suggest_int("n_estimators", 100, 400, step=50),
        "max_depth": trial.suggest_int("max_depth", 4, 14),
        "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 50, log=True),
        "max_features": trial.suggest_categorical("max_features", ["sqrt", "log2", 0.5]),
        "class_weight": trial.suggest_categorical("class_weight", ["balanced", "balanced_subsample"]),
    }


def _xgboost(params: dict[str, Any], random_state: int) -> XGBClassifier:
    return XGBClassifier(random_state=random_state, **params)


def _sample_xgboost(trial: optuna.Trial) -> dict[str, Any]:
    return {
        "n_estimators": trial.suggest_int("n_estimators", 100, 600, step=50),
        "max_depth": trial.suggest_int("max_depth", 2, 6),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 50, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 20.0, log=True),
    }


def _lightgbm(params: dict[str, Any], random_state: int) -> LGBMClassifier:
    return LGBMClassifier(random_state=random_state, **params)


def _sample_lightgbm(trial: optuna.Trial) -> dict[str, Any]:
    return {
        "n_estimators": trial.suggest_int("n_estimators", 100, 600, step=50),
        "num_leaves": trial.suggest_int("num_leaves", 8, 48, log=True),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 20, 200, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 20.0, log=True),
    }


CANDIDATES: dict[str, CandidateModel] = {
    "logistic_regression": CandidateModel(
        name="logistic_regression",
        display_name="Logistic Regression",
        factory=_logistic_regression,
        sample_params=_sample_logistic_regression,
        default_params={"C": 1.0, "class_weight": "balanced", "max_iter": 2000},
    ),
    "random_forest": CandidateModel(
        name="random_forest",
        display_name="Random Forest",
        factory=_random_forest,
        sample_params=_sample_random_forest,
        default_params={"n_estimators": 200, "max_depth": 8, "class_weight": "balanced", "n_jobs": -1},
    ),
    "xgboost": CandidateModel(
        name="xgboost",
        display_name="XGBoost",
        factory=_xgboost,
        sample_params=_sample_xgboost,
        default_params={
            "n_estimators": 300,
            "max_depth": 4,
            "learning_rate": 0.05,
            "tree_method": "hist",
            "eval_metric": "logloss",
            "n_jobs": 4,
        },
    ),
    "lightgbm": CandidateModel(
        name="lightgbm",
        display_name="LightGBM",
        factory=_lightgbm,
        sample_params=_sample_lightgbm,
        default_params={
            "n_estimators": 300,
            "learning_rate": 0.05,
            "class_weight": "balanced",
            "subsample_freq": 1,
            "deterministic": True,
            "force_row_wise": True,
            # ~12k rows: extra threads only add contention (5-fold CV is ~6x slower with n_jobs=-1).
            "n_jobs": 1,
            "verbose": -1,
        },
    ),
}

LEGACY_MODEL_TYPES = {
    "RandomForestClassifier": "random_forest",
    "RandomForestClassifier-V2": "random_forest",
}


def get_candidate(name: str) -> CandidateModel:
    """Look up a candidate by name (legacy ``RandomForestClassifier`` labels are accepted).

    Raises:
        KeyError: for an unknown algorithm name.
    """
    key = LEGACY_MODEL_TYPES.get(name, name)
    if key not in CANDIDATES:
        raise KeyError(f"Unknown candidate model '{name}'. Available: {sorted(CANDIDATES)}")
    return CANDIDATES[key]
