"""Entrypoint: run PSI + Evidently drift analysis; exit code 1 signals drift."""

import sys

from credit_risk.config import setup_logging
from credit_risk.monitoring.drift import run_drift_analysis

if __name__ == "__main__":
    setup_logging()
    result = run_drift_analysis()
    sys.exit(1 if result.is_drifted and "--fail-on-drift" in sys.argv else 0)
