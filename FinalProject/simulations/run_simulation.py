"""Module: run_simulation.py
Master runner for end-to-end traffic and drift simulation.
Runs Phase 1 (Baseline stability) and Phase 2 (Drift shock to trigger observability alerts).
Supports API v1 and X-API-Key authentication.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.scenarios import (  # noqa: E402
    FraudAttackScenario,
    GenZDriftScenario,
    HolidaySpikeScenario,
    NormalTrafficScenario,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SimulationRunner")

DEFAULT_API_URL = os.getenv("API_URL", "http://localhost:18020")
DEFAULT_API_KEY = os.getenv("API_KEY", "local-dev-key-change-me")


def check_api_health(base_url: str) -> bool:
    """Verifies that the Credit Risk Scoring API is up and healthy."""
    for path in ["/health/live", "/health"]:
        health_url = f"{base_url.rstrip('/')}{path}"
        try:
            resp = requests.get(health_url, timeout=3.0)
            if resp.status_code == 200:
                logger.info("API is healthy at %s", health_url)
                return True
        except Exception as exc:
            logger.debug("Probe failed at %s: %s", health_url, exc)
    logger.warning("API health check failed at %s", base_url)
    return False


def run_full_lifecycle_simulation(
    base_url: str,
    count: int = 40,
    delay: float = 0.02,
    api_key: str = DEFAULT_API_KEY,
):
    """Executes a 2-phase production lifecycle simulation: Normal -> Drift Shock."""
    clean_url = base_url.rstrip("/")
    if not clean_url.endswith("/predict"):
        predict_url = f"{clean_url}/api/v1/predict"
    else:
        predict_url = clean_url

    logger.info("=================================================================")
    logger.info("🎬 PHASE 1: Baseline Normal Traffic Simulation (%d requests)", count)
    logger.info("=================================================================")
    normal_scenario = NormalTrafficScenario(api_url=predict_url, api_key=api_key)
    res_normal = normal_scenario.run(count=count, delay_sec=delay)
    logger.info("Phase 1 Summary: %s", res_normal)

    time.sleep(1.0)

    logger.info("=================================================================")
    logger.info("🚨 PHASE 2: Gen-Z Acquisition Drift Shock Simulation (%d requests)", count)
    logger.info("=================================================================")
    drift_scenario = GenZDriftScenario(api_url=predict_url, api_key=api_key)
    res_drift = drift_scenario.run(count=count, delay_sec=delay)
    logger.info("Phase 2 Summary: %s", res_drift)

    logger.info("=================================================================")
    logger.info("🎉 SIMULATION LIFECYCLE COMPLETED SUCCESSFULLY!")
    logger.info("Check Grafana Dashboard (http://localhost:13000) for real-time drift metrics.")
    logger.info("=================================================================")


def main():
    parser = argparse.ArgumentParser(description="Credit Risk Real-Time Traffic & Drift Simulation Suite")
    parser.add_argument(
        "--api-url", default=DEFAULT_API_URL, help="Base URL of Credit Risk API (default: localhost:18020)"
    )
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API Key for X-API-Key header auth")
    parser.add_argument(
        "--scenario",
        choices=["all", "normal", "genz_drift", "holiday_spike", "fraud_attack"],
        default="all",
        help="Simulation scenario to execute",
    )
    parser.add_argument("--count", type=int, default=40, help="Number of simulated applications")
    parser.add_argument("--delay", type=float, default=0.02, help="Delay between requests in seconds")
    parser.add_argument("--skip-health-check", action="store_true", help="Skip initial API health verification")

    args = parser.parse_args()

    clean_url = args.api_url.rstrip("/")
    if not clean_url.endswith("/predict"):
        predict_url = f"{clean_url}/api/v1/predict"
    else:
        predict_url = clean_url

    if not args.skip_health_check:
        logger.info("Checking API reachability at %s...", args.api_url)
        if not check_api_health(clean_url):
            logger.error("API is offline at %s. Please start services with: make up", args.api_url)
            sys.exit(1)

    if args.scenario == "all":
        run_full_lifecycle_simulation(args.api_url, count=args.count, delay=args.delay, api_key=args.api_key)
    elif args.scenario == "normal":
        scenario = NormalTrafficScenario(api_url=predict_url, api_key=args.api_key)
        res = scenario.run(count=args.count, delay_sec=args.delay)
        logger.info("Normal scenario completed: %s", res)
    elif args.scenario == "genz_drift":
        scenario = GenZDriftScenario(api_url=predict_url, api_key=args.api_key)
        res = scenario.run(count=args.count, delay_sec=args.delay)
        logger.info("GenZ drift scenario completed: %s", res)
    elif args.scenario == "holiday_spike":
        scenario = HolidaySpikeScenario(api_url=predict_url, api_key=args.api_key)
        res = scenario.run(count=args.count, delay_sec=args.delay)
        logger.info("Holiday spike scenario completed: %s", res)
    elif args.scenario == "fraud_attack":
        scenario = FraudAttackScenario(api_url=predict_url, api_key=args.api_key)
        res = scenario.run(count=args.count, delay_sec=args.delay)
        logger.info("Fraud attack scenario completed: %s", res)


if __name__ == "__main__":
    main()
