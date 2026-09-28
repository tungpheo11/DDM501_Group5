"""
Script: sample_predict.py
Sends sample prediction requests to the Credit Risk Scoring API.
"""

import requests
import json

API_URL = "http://localhost:18020"


def test_prediction():
    # 1. Check health
    health_resp = requests.get(f"{API_URL}/health")
    print(f"Health Status: {health_resp.status_code}")
    print(json.dumps(health_resp.json(), indent=2))

    # 2. Low-risk customer (older, high limit, pays on time)
    good_customer = {
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
    print("\n--- Sending Low Risk Customer Request ---")
    resp_good = requests.post(f"{API_URL}/predict", json=good_customer)
    print(f"Status: {resp_good.status_code}")
    print(json.dumps(resp_good.json(), indent=2))

    # 3. High-risk customer (delayed payments, high bill, low repayment)
    high_risk_customer = {
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
    print("\n--- Sending High Risk Customer Request ---")
    resp_risk = requests.post(f"{API_URL}/predict", json=high_risk_customer)
    print(f"Status: {resp_risk.status_code}")
    print(json.dumps(resp_risk.json(), indent=2))


if __name__ == "__main__":
    test_prediction()
