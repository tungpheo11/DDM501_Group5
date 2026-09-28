"""Module: scenarios.py
Defines reusable traffic and drift simulation scenarios for observability and alert testing.
Supports API v1 contracts and X-API-Key authentication.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from simulations.data_generator import CreditDataGenerator

logger = logging.getLogger("SimulationScenarios")

DEFAULT_API_URL = os.getenv("API_URL", "http://localhost:18020/api/v1/predict")
DEFAULT_API_KEY = os.getenv("API_KEY", "local-dev-key-change-me")


class BaseScenario:
    """Base class for all traffic simulation scenarios."""

    def __init__(
        self,
        api_url: str | None = None,
        generator: CreditDataGenerator | None = None,
        api_key: str | None = None,
    ):
        self.api_url = api_url or DEFAULT_API_URL
        self.generator = generator or CreditDataGenerator()
        self.api_key = api_key or DEFAULT_API_KEY

    @property
    def headers(self) -> dict[str, str]:
        if self.api_key:
            return {"X-API-Key": self.api_key}
        return {}

    def run(self, count: int = 50, delay_sec: float = 0.02) -> dict[str, Any]:
        raise NotImplementedError


class NormalTrafficScenario(BaseScenario):
    """Simulates healthy, stable baseline applicant traffic (PSI < 0.05)."""

    def run(self, count: int = 50, delay_sec: float = 0.02) -> dict[str, Any]:
        logger.info("Executing NormalTrafficScenario (%d applications)...", count)
        stats = {
            "scenario": "NormalTraffic",
            "total_sent": count,
            "APPROVE": 0,
            "REVIEW": 0,
            "DECLINE": 0,
            "errors": 0,
            "approved_volume_ntd": 0.0,
            "blocked_exposure_ntd": 0.0,
        }
        latencies = []

        for _ in range(count):
            payload = self.generator.generate_normal_sample()
            try:
                t0 = time.time()
                resp = requests.post(self.api_url, json=payload, headers=self.headers, timeout=5.0)
                latencies.append((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    decision = data.get("risk_decision", "APPROVE")
                    stats[decision] = stats.get(decision, 0) + 1
                    if decision == "APPROVE":
                        stats["approved_volume_ntd"] += data.get("recommended_limit_ntd", 0.0)
                    elif decision == "DECLINE":
                        stats["blocked_exposure_ntd"] += payload["LIMIT_BAL"]
                else:
                    stats["errors"] += 1
            except Exception:
                stats["errors"] += 1

            if delay_sec > 0:
                time.sleep(delay_sec)

        stats["avg_latency_ms"] = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        return stats


class GenZDriftScenario(BaseScenario):
    """Simulates viral Gen-Z acquisition campaign with severe demographic and covariate drift (PSI >= 0.25)."""

    def run(self, count: int = 60, delay_sec: float = 0.02) -> dict[str, Any]:
        logger.info("Executing GenZDriftScenario (%d applications)...", count)
        stats = {
            "scenario": "GenZDrift",
            "total_sent": count,
            "APPROVE": 0,
            "REVIEW": 0,
            "DECLINE": 0,
            "errors": 0,
            "approved_volume_ntd": 0.0,
            "blocked_exposure_ntd": 0.0,
        }
        latencies = []

        for _ in range(count):
            payload = self.generator.generate_genz_drift_sample()
            try:
                t0 = time.time()
                resp = requests.post(self.api_url, json=payload, headers=self.headers, timeout=5.0)
                latencies.append((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    decision = data.get("risk_decision", "REVIEW")
                    stats[decision] = stats.get(decision, 0) + 1
                    if decision == "APPROVE":
                        stats["approved_volume_ntd"] += data.get("recommended_limit_ntd", 0.0)
                    elif decision == "DECLINE":
                        stats["blocked_exposure_ntd"] += payload["LIMIT_BAL"]
                else:
                    stats["errors"] += 1
            except Exception:
                stats["errors"] += 1

            if delay_sec > 0:
                time.sleep(delay_sec)

        stats["avg_latency_ms"] = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        return stats


class HolidaySpikeScenario(BaseScenario):
    """Simulates festival shopping surge with high credit line utilization."""

    def run(self, count: int = 50, delay_sec: float = 0.02) -> dict[str, Any]:
        logger.info("Executing HolidaySpikeScenario (%d applications)...", count)
        stats = {
            "scenario": "HolidaySpike",
            "total_sent": count,
            "APPROVE": 0,
            "REVIEW": 0,
            "DECLINE": 0,
            "errors": 0,
            "approved_volume_ntd": 0.0,
            "blocked_exposure_ntd": 0.0,
        }
        latencies = []

        for _ in range(count):
            payload = self.generator.generate_holiday_spike_sample()
            try:
                t0 = time.time()
                resp = requests.post(self.api_url, json=payload, headers=self.headers, timeout=5.0)
                latencies.append((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    decision = data.get("risk_decision", "APPROVE")
                    stats[decision] = stats.get(decision, 0) + 1
                    if decision == "APPROVE":
                        stats["approved_volume_ntd"] += data.get("recommended_limit_ntd", 0.0)
                    elif decision == "DECLINE":
                        stats["blocked_exposure_ntd"] += payload["LIMIT_BAL"]
                else:
                    stats["errors"] += 1
            except Exception:
                stats["errors"] += 1

            if delay_sec > 0:
                time.sleep(delay_sec)

        stats["avg_latency_ms"] = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        return stats


class FraudAttackScenario(BaseScenario):
    """Simulates delinquent / syndicate attack with elevated default probabilities."""

    def run(self, count: int = 50, delay_sec: float = 0.02) -> dict[str, Any]:
        logger.info("Executing FraudAttackScenario (%d applications)...", count)
        stats = {
            "scenario": "FraudAttack",
            "total_sent": count,
            "APPROVE": 0,
            "REVIEW": 0,
            "DECLINE": 0,
            "errors": 0,
            "approved_volume_ntd": 0.0,
            "blocked_exposure_ntd": 0.0,
        }
        latencies = []

        for _ in range(count):
            payload = self.generator.generate_delinquent_sample()
            try:
                t0 = time.time()
                resp = requests.post(self.api_url, json=payload, headers=self.headers, timeout=5.0)
                latencies.append((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    decision = data.get("risk_decision", "DECLINE")
                    stats[decision] = stats.get(decision, 0) + 1
                    if decision == "APPROVE":
                        stats["approved_volume_ntd"] += data.get("recommended_limit_ntd", 0.0)
                    elif decision == "DECLINE":
                        stats["blocked_exposure_ntd"] += payload["LIMIT_BAL"]
                else:
                    stats["errors"] += 1
            except Exception:
                stats["errors"] += 1

            if delay_sec > 0:
                time.sleep(delay_sec)

        stats["avg_latency_ms"] = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        return stats
