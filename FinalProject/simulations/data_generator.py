"""Module: data_generator.py
Generates realistic financial applicant records for real-time inference and drift simulation.
Alings with UCI Credit Default 23-feature schema.
"""

from __future__ import annotations

import random
from typing import Any


class CreditDataGenerator:
    """Generates synthetic credit applicant feature vectors with calibrated drift injection."""

    def __init__(self, seed: int | None = None):
        if seed is not None:
            random.seed(seed)

    def generate_normal_sample(self) -> dict[str, Any]:
        """Baseline prime applicant: mature age, stable limit, disciplined repayments (PAY_0=0)."""
        limit_bal = float(random.choice([150000, 200000, 250000, 300000, 400000]))
        age = random.randint(35, 52)
        bill_base = limit_bal * random.uniform(0.08, 0.25)

        return {
            "LIMIT_BAL": limit_bal,
            "SEX": random.choice([1, 2]),
            "EDUCATION": random.choice([1, 2]),
            "MARRIAGE": random.choice([1, 2]),
            "AGE": age,
            "PAY_0": 0,
            "PAY_2": 0,
            "PAY_3": 0,
            "PAY_4": 0,
            "PAY_5": 0,
            "PAY_6": 0,
            "BILL_AMT1": round(bill_base * random.uniform(0.9, 1.1), 2),
            "BILL_AMT2": round(bill_base * random.uniform(0.85, 1.05), 2),
            "BILL_AMT3": round(bill_base * random.uniform(0.8, 1.0), 2),
            "BILL_AMT4": round(bill_base * random.uniform(0.75, 0.95), 2),
            "BILL_AMT5": round(bill_base * random.uniform(0.7, 0.9), 2),
            "BILL_AMT6": round(bill_base * random.uniform(0.65, 0.85), 2),
            "PAY_AMT1": round(bill_base * random.uniform(0.8, 1.2), 2),
            "PAY_AMT2": round(bill_base * random.uniform(0.8, 1.2), 2),
            "PAY_AMT3": round(bill_base * random.uniform(0.8, 1.2), 2),
            "PAY_AMT4": round(bill_base * random.uniform(0.8, 1.2), 2),
            "PAY_AMT5": round(bill_base * random.uniform(0.8, 1.2), 2),
            "PAY_AMT6": round(bill_base * random.uniform(0.8, 1.2), 2),
        }

    def generate_genz_drift_sample(self) -> dict[str, Any]:
        """Demographic & covariate drift: Young gig-economy applicants (19-25yo) with lower limit and PAY_0=1."""
        limit_bal = float(random.choice([20000, 30000, 40000, 50000]))
        age = random.randint(19, 25)
        bill_base = limit_bal * random.uniform(0.35, 0.65)
        pay_0 = random.choice([1, 1, 0, 1])

        return {
            "LIMIT_BAL": limit_bal,
            "SEX": random.choice([1, 2]),
            "EDUCATION": random.choice([2, 3]),
            "MARRIAGE": 2,  # Single
            "AGE": age,
            "PAY_0": pay_0,
            "PAY_2": random.choice([0, 1, -1]),
            "PAY_3": 0,
            "PAY_4": 0,
            "PAY_5": 0,
            "PAY_6": 0,
            "BILL_AMT1": round(bill_base * random.uniform(0.95, 1.15), 2),
            "BILL_AMT2": round(bill_base * random.uniform(0.9, 1.1), 2),
            "BILL_AMT3": round(bill_base * random.uniform(0.8, 1.0), 2),
            "BILL_AMT4": round(bill_base * random.uniform(0.7, 0.9), 2),
            "BILL_AMT5": round(bill_base * random.uniform(0.6, 0.8), 2),
            "BILL_AMT6": round(bill_base * random.uniform(0.5, 0.7), 2),
            "PAY_AMT1": round(bill_base * random.uniform(0.3, 0.7), 2),
            "PAY_AMT2": round(bill_base * random.uniform(0.4, 0.8), 2),
            "PAY_AMT3": round(bill_base * random.uniform(0.5, 0.9), 2),
            "PAY_AMT4": round(bill_base * random.uniform(0.5, 0.9), 2),
            "PAY_AMT5": round(bill_base * random.uniform(0.5, 0.9), 2),
            "PAY_AMT6": round(bill_base * random.uniform(0.5, 0.9), 2),
        }

    def generate_holiday_spike_sample(self) -> dict[str, Any]:
        """Seasonal utilization shock: High spenders with 80-92% utilization and large bill amounts."""
        limit_bal = float(random.choice([100000, 150000, 200000, 250000]))
        age = random.randint(30, 48)
        bill_base = limit_bal * random.uniform(0.80, 0.92)

        return {
            "LIMIT_BAL": limit_bal,
            "SEX": random.choice([1, 2]),
            "EDUCATION": random.choice([1, 2]),
            "MARRIAGE": random.choice([1, 2]),
            "AGE": age,
            "PAY_0": random.choice([0, -1, 0]),
            "PAY_2": 0,
            "PAY_3": 0,
            "PAY_4": 0,
            "PAY_5": 0,
            "PAY_6": 0,
            "BILL_AMT1": round(bill_base, 2),
            "BILL_AMT2": round(bill_base * 0.92, 2),
            "BILL_AMT3": round(bill_base * 0.75, 2),
            "BILL_AMT4": round(bill_base * 0.50, 2),
            "BILL_AMT5": round(bill_base * 0.40, 2),
            "BILL_AMT6": round(bill_base * 0.35, 2),
            "PAY_AMT1": round(bill_base * 0.35, 2),
            "PAY_AMT2": round(bill_base * 0.30, 2),
            "PAY_AMT3": round(bill_base * 0.30, 2),
            "PAY_AMT4": round(bill_base * 0.25, 2),
            "PAY_AMT5": round(bill_base * 0.25, 2),
            "PAY_AMT6": round(bill_base * 0.25, 2),
        }

    def generate_delinquent_sample(self) -> dict[str, Any]:
        """Severe delinquency: High default risk with PAY_0 >= 2 and maxed out credit lines."""
        limit_bal = float(random.choice([50000, 80000, 100000]))
        age = random.randint(28, 48)
        bill_base = limit_bal * random.uniform(0.95, 0.99)

        return {
            "LIMIT_BAL": limit_bal,
            "SEX": random.choice([1, 2]),
            "EDUCATION": random.choice([1, 2, 3]),
            "MARRIAGE": random.choice([1, 2]),
            "AGE": age,
            "PAY_0": random.choice([2, 3, 2]),
            "PAY_2": random.choice([2, 2, 1]),
            "PAY_3": 2,
            "PAY_4": 1,
            "PAY_5": 0,
            "PAY_6": 0,
            "BILL_AMT1": round(bill_base, 2),
            "BILL_AMT2": round(bill_base * 0.98, 2),
            "BILL_AMT3": round(bill_base * 0.96, 2),
            "BILL_AMT4": round(bill_base * 0.92, 2),
            "BILL_AMT5": round(bill_base * 0.88, 2),
            "BILL_AMT6": round(bill_base * 0.85, 2),
            "PAY_AMT1": round(bill_base * 0.04, 2),
            "PAY_AMT2": round(bill_base * 0.04, 2),
            "PAY_AMT3": round(bill_base * 0.04, 2),
            "PAY_AMT4": round(bill_base * 0.04, 2),
            "PAY_AMT5": round(bill_base * 0.04, 2),
            "PAY_AMT6": round(bill_base * 0.04, 2),
        }

    def generate_sample_by_scenario(self, scenario: str) -> dict[str, Any]:
        """Selects sample distribution based on target market regime."""
        r = random.random()
        if scenario == "normal":
            if r < 0.80:
                return self.generate_normal_sample()
            elif r < 0.90:
                return self.generate_holiday_spike_sample()
            else:
                return self.generate_genz_drift_sample()

        elif scenario == "genz_drift":
            if r < 0.75:
                return self.generate_genz_drift_sample()
            elif r < 0.90:
                return self.generate_normal_sample()
            else:
                return self.generate_delinquent_sample()

        elif scenario == "holiday_spike":
            if r < 0.65:
                return self.generate_holiday_spike_sample()
            elif r < 0.85:
                return self.generate_normal_sample()
            else:
                return self.generate_genz_drift_sample()

        elif scenario == "fraud_attack":
            if r < 0.70:
                return self.generate_delinquent_sample()
            elif r < 0.85:
                return self.generate_genz_drift_sample()
            else:
                return self.generate_normal_sample()

        return self.generate_normal_sample()

    def generate_batch(self, count: int, scenario: str = "normal") -> list[dict[str, Any]]:
        """Generates a batch of applicant records."""
        return [self.generate_sample_by_scenario(scenario) for _ in range(count)]
