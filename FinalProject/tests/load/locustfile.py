"""Locust scenario for the scoring API: mostly single predictions, some batches and health probes.

Standalone::

    locust -f tests/load/locustfile.py --host http://localhost:18020            # web UI on :8089
    locust -f tests/load/locustfile.py --host http://localhost:18020 --headless -u 20 -r 10 -t 60s

The API key is read from ``LOAD_API_KEY`` or the first entry of ``API_KEYS`` in ``.env``.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

from locust import HttpUser, between, task

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAY_COLUMNS = ("PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6")


def _api_key() -> str:
    if os.environ.get("LOAD_API_KEY"):
        return os.environ["LOAD_API_KEY"]
    for name in (".env", ".env.example"):
        path = PROJECT_ROOT / name
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("API_KEYS="):
                    return line.partition("=")[2].split(",")[0].strip()
    return ""


def random_cardholder(rng: random.Random) -> dict[str, float]:
    """Cardholder drawn from ranges that match the training data (UCI Credit Default)."""
    limit = float(rng.choice([20000, 50000, 80000, 120000, 200000, 360000, 500000]))
    delay = rng.choices([-1, 0, 1, 2, 3], weights=[20, 55, 12, 10, 3])[0]
    bills = [round(limit * rng.uniform(0.0, 0.9), 0) for _ in range(6)]
    return {
        "LIMIT_BAL": limit,
        "SEX": rng.choice([1, 2]),
        "EDUCATION": rng.choice([1, 2, 3]),
        "MARRIAGE": rng.choice([1, 2]),
        "AGE": rng.randint(21, 65),
        **{col: max(-1, delay + rng.choice([-1, 0, 0, 1])) for col in PAY_COLUMNS},
        **{f"BILL_AMT{i}": bills[i - 1] for i in range(1, 7)},
        **{f"PAY_AMT{i}": round(bills[i - 1] * rng.uniform(0.0, 0.3), 0) for i in range(1, 7)},
    }


class ScoringUser(HttpUser):
    """Card management system / mobile app backend traffic against the scoring API.

    Single calls are cardholder limit-increase requests; batches of 10 stand in for the
    post-statement limit-review job.
    """

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.client.headers.update({"X-API-Key": _api_key(), "Content-Type": "application/json"})
        self.rng = random.Random()

    @task(20)
    def predict(self) -> None:
        self.client.post("/api/v1/predict", json=random_cardholder(self.rng), name="POST /api/v1/predict")

    @task(2)
    def predict_batch(self) -> None:
        payload = {"cardholders": [random_cardholder(self.rng) for _ in range(10)]}
        self.client.post("/api/v1/predict/batch", json=payload, name="POST /api/v1/predict/batch (10)")

    @task(1)
    def readiness(self) -> None:
        self.client.get("/health/ready", name="GET /health/ready")
