"""Entrypoint: validate data, tune candidates (Optuna + stratified CV), gate and register the champion."""

import argparse
import sys

from credit_risk.config import get_logger, setup_logging
from credit_risk.data.validation import DataValidationError
from credit_risk.training.train import run_training_pipeline

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-trials", type=int, default=None, help="Optuna trials per candidate (overrides config)")
    parser.add_argument(
        "--candidates", nargs="+", default=None, help="Subset of: logistic_regression random_forest xgboost lightgbm"
    )
    parser.add_argument("--no-register", action="store_true", help="Log runs but skip registry + promotion gate")
    parser.add_argument("--no-readme", action="store_true", help="Do not refresh the README results block")
    args = parser.parse_args()

    setup_logging()
    try:
        outcome = run_training_pipeline(
            n_trials=args.n_trials,
            candidates=args.candidates,
            register=not args.no_register,
            sync_readme=not args.no_readme,
        )
    except DataValidationError as exc:
        get_logger(__name__).error("Training aborted: %s", exc)
        sys.exit(2)

    print(f"Selected: {outcome.selected.display_name} | gate: {'PROMOTE' if outcome.gate.promote else 'KEEP'}")
    print(f"Registered version: {outcome.registered_version} | @champion: {outcome.champion_version}")
    print(f"Report: {outcome.report_paths['markdown']}")
