"""Send one low-risk and one high-risk sample request to the scoring API."""

import argparse
import json
import os

import requests

GOOD_CUSTOMER = {
    "LIMIT_BAL": 200000.0,
    "SEX": 2,
    "EDUCATION": 1,
    "MARRIAGE": 2,
    "AGE": 38,
    "PAY_0": 0,
    "PAY_2": 0,
    "PAY_3": 0,
    "PAY_4": 0,
    "PAY_5": 0,
    "PAY_6": 0,
    "BILL_AMT1": 15000.0,
    "BILL_AMT2": 14000.0,
    "BILL_AMT3": 13000.0,
    "BILL_AMT4": 12000.0,
    "BILL_AMT5": 11000.0,
    "BILL_AMT6": 10000.0,
    "PAY_AMT1": 5000.0,
    "PAY_AMT2": 5000.0,
    "PAY_AMT3": 5000.0,
    "PAY_AMT4": 5000.0,
    "PAY_AMT5": 5000.0,
    "PAY_AMT6": 5000.0,
}

HIGH_RISK_CUSTOMER = {
    "LIMIT_BAL": 20000.0,
    "SEX": 1,
    "EDUCATION": 2,
    "MARRIAGE": 1,
    "AGE": 23,
    "PAY_0": 2,
    "PAY_2": 2,
    "PAY_3": 2,
    "PAY_4": 2,
    "PAY_5": 2,
    "PAY_6": 2,
    "BILL_AMT1": 19500.0,
    "BILL_AMT2": 19800.0,
    "BILL_AMT3": 19900.0,
    "BILL_AMT4": 20000.0,
    "BILL_AMT5": 20100.0,
    "BILL_AMT6": 20200.0,
    "PAY_AMT1": 0.0,
    "PAY_AMT2": 0.0,
    "PAY_AMT3": 0.0,
    "PAY_AMT4": 0.0,
    "PAY_AMT5": 0.0,
    "PAY_AMT6": 0.0,
}


def main(api_url: str, api_key: str) -> None:
    """Print /health/ready and two /api/v1/predict responses."""
    health = requests.get(f"{api_url}/health/ready", timeout=5)
    print(f"Readiness: {health.status_code}")
    print(json.dumps(health.json(), indent=2))

    headers = {"X-API-Key": api_key} if api_key else {}
    for label, payload in (("Low Risk", GOOD_CUSTOMER), ("High Risk", HIGH_RISK_CUSTOMER)):
        print(f"\n--- Sending {label} Customer Request ---")
        response = requests.post(f"{api_url}/api/v1/predict", json=payload, headers=headers, timeout=5)
        print(f"Status: {response.status_code}")
        print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:18020"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY") or os.getenv("API_KEYS", "").split(",")[0].strip())
    args = parser.parse_args()
    main(args.api_url.rstrip("/"), args.api_key)
