"""Measure client-side latency of POST /api/v1/predict against a running API (``make bench``).

Sends real cardholders from data/processed/stream_normal.csv sequentially over a
keep-alive session after a warm-up, then prints p50/p95/p99 and exits non-zero
when p95 exceeds the budget (default 100 ms). Optional ``--output`` writes JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEATURES = [
    "LIMIT_BAL",
    "SEX",
    "EDUCATION",
    "MARRIAGE",
    "AGE",
    *(f"PAY_{i}" for i in (0, 2, 3, 4, 5, 6)),
    *(f"BILL_AMT{i}" for i in range(1, 7)),
    *(f"PAY_AMT{i}" for i in range(1, 7)),
]


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


def main(api_url: str, api_key: str, requests_count: int, warmup: int, budget_ms: float, output: Path | None) -> int:
    frame = pd.read_csv(PROJECT_ROOT / "data" / "processed" / "stream_normal.csv")[FEATURES]
    payloads = frame.sample(n=requests_count + warmup, replace=True, random_state=42).to_dict("records")
    session = requests.Session()
    session.headers.update({"X-API-Key": api_key})
    url = f"{api_url.rstrip('/')}/api/v1/predict"

    latencies: list[float] = []
    server_latencies: list[float] = []
    errors = 0
    for index, payload in enumerate(payloads):
        start = time.perf_counter()
        response = session.post(url, json=payload, timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if index < warmup:
            continue
        if response.status_code != 200:
            errors += 1
            continue
        latencies.append(elapsed_ms)
        server_latencies.append(float(response.json()["latency_ms"]))

    if not latencies:
        print("No successful requests.")
        return 2
    result: dict[str, Any] = {
        "endpoint": url,
        "requests": len(latencies),
        "errors": errors,
        "client_ms": {
            "mean": round(statistics.fmean(latencies), 2),
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
            "max": round(max(latencies), 2),
        },
        "server_model_ms_p95": round(percentile(server_latencies, 95), 2),
        "budget_p95_ms": budget_ms,
    }
    result["pass"] = result["client_ms"]["p95"] < budget_ms and errors == 0
    print(json.dumps(result, indent=2))
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:18020"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY") or os.getenv("API_KEYS", "").split(",")[0].strip())
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--budget-ms", type=float, default=100.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    sys.exit(main(args.api_url, args.api_key, args.requests, args.warmup, args.budget_ms, args.output))
