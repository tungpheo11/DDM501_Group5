"""Entrypoint: champion/challenger retraining with promotion and API hot reload."""

import argparse

from credit_risk.config import setup_logging
from credit_risk.training.retrain import run_retraining_pipeline

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-reload", action="store_true", help="Do not call the API /api/v1/model/reload endpoint")
    args = parser.parse_args()

    setup_logging()
    run_retraining_pipeline(reload_api=not args.no_reload)
