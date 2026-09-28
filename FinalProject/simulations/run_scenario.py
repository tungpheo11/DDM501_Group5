"""Traffic scenarios for the running stack (``make simulate SCENARIO=<name>``).

========  ==================================================================  =============================
scenario  traffic                                                             expected signal
========  ==================================================================  =============================
normal    replay of ``data/processed/stream_normal.csv`` (same population     no drift, alerts resolve
          as the reference)
drift     replay of ``stream_drifted.csv`` - Gen-Z acquisition campaign        DataDriftDetected (AGE PSI),
          (mean age 26 vs 38) + ``campaign_drift`` personas                   drift_monitoring -> retrain
attack    coordinated delinquency: ``fraud_attack`` personas (70% maxed-out    decline spike,
          speculators with PAY_0 >= 2)                                        PredictionDistributionShift
load      concurrent replay for ``--duration`` seconds; client p50/p95/p99    HighLatencyP95 (with
                                                                              ``make chaos-latency``)
outage    stops ``--target`` (default api) for ``--down-seconds`` while       APIDown fires, then resolves;
          traffic continues, restarts it and measures recovery                 recovery time reported
========  ==================================================================  =============================

A JSON summary of every run is written to ``reports/simulations/``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from persona_simulator import sample_persona_by_mode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports" / "simulations"
FEATURES = [
    "LIMIT_BAL", "SEX", "EDUCATION", "MARRIAGE", "AGE",
    "PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6",
    "BILL_AMT1", "BILL_AMT2", "BILL_AMT3", "BILL_AMT4", "BILL_AMT5", "BILL_AMT6",
    "PAY_AMT1", "PAY_AMT2", "PAY_AMT3", "PAY_AMT4", "PAY_AMT5", "PAY_AMT6",
]  # fmt: skip

Payload = dict[str, Any]


def read_env_file(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path is None or not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_api_key(env: dict[str, str]) -> str:
    for source in (os.environ, env):
        key = source.get("API_KEY") or source.get("API_KEYS", "").split(",")[0].strip()
        if key:
            return key
    return ""


def replay_payloads(csv_name: str, *, shuffle: bool = True, seed: int = 42) -> list[Payload]:
    frame = pd.read_csv(PROCESSED_DIR / csv_name)
    records = frame[FEATURES].to_dict("records")
    if shuffle:
        random.Random(seed).shuffle(records)
    return records


def persona_payloads(mode: str, count: int) -> list[Payload]:
    return [sample_persona_by_mode(mode)[1] for _ in range(count)]


def cycle(payloads: list[Payload]) -> Iterator[Payload]:
    while True:
        yield from payloads


@dataclass
class RunStats:
    """Thread-safe counters for one scenario run."""

    latencies_ms: list[float] = field(default_factory=list)
    status: Counter[str] = field(default_factory=Counter)
    decisions: Counter[str] = field(default_factory=Counter)
    probabilities: list[float] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, status: str, latency_ms: float, body: dict[str, Any] | None) -> None:
        """Record one response (``status`` is the HTTP code or the exception name)."""
        with self.lock:
            self.status[status] += 1
            self.latencies_ms.append(latency_ms)
            if body:
                self.decisions[body.get("risk_decision", "?")] += 1
                if "default_probability" in body:
                    self.probabilities.append(float(body["default_probability"]))

    def summary(self) -> dict[str, Any]:
        """Counts, decision mix and client-side latency percentiles."""
        with self.lock:
            lat = sorted(self.latencies_ms)
            total = sum(self.status.values())
            ok = self.status.get("200", 0)

            def pct(q: float) -> float:
                return round(lat[min(len(lat) - 1, int(q * len(lat)))], 1) if lat else 0.0

            return {
                "requests": total,
                "success": ok,
                "errors": total - ok,
                "status_codes": dict(self.status),
                "decisions": dict(self.decisions),
                "decision_share": {k: round(v / max(ok, 1), 3) for k, v in self.decisions.items()},
                "mean_default_probability": (
                    round(statistics.fmean(self.probabilities), 4) if self.probabilities else None
                ),
                "latency_ms": {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99), "max": pct(1.0)},
            }


class ScoringClient:
    """Minimal thread-safe client for ``POST /api/v1/predict`` (one session per thread)."""

    def __init__(self, api_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.predict_url = f"{api_url.rstrip('/')}/api/v1/predict"
        self.api_url = api_url.rstrip("/")
        self.headers = {"X-API-Key": api_key} if api_key else {}
        self.timeout = timeout
        self._local = threading.local()

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
            self._local.session.headers.update(self.headers)
        return self._local.session

    def predict(self, payload: Payload, stats: RunStats) -> None:
        """Score one application and record the outcome in ``stats``."""
        started = time.perf_counter()
        try:
            response = self._session().post(self.predict_url, json=payload, timeout=self.timeout)
            body = response.json() if response.status_code == 200 else None
            stats.record(str(response.status_code), (time.perf_counter() - started) * 1000, body)
        except requests.RequestException as exc:
            stats.record(type(exc).__name__, (time.perf_counter() - started) * 1000, None)

    def ready(self) -> bool:
        """True when ``/health/ready`` answers 200."""
        return self._probe("/health/ready")

    def alive(self) -> bool:
        """True when ``/health/live`` answers 200 (process up, model not required)."""
        return self._probe("/health/live")

    def _probe(self, path: str) -> bool:
        try:
            return requests.get(f"{self.api_url}{path}", timeout=3).status_code == 200
        except requests.RequestException:
            return False


def send_all(client: ScoringClient, payloads: list[Payload], concurrency: int, label: str) -> RunStats:
    stats = RunStats()
    print(f"==> {label}: {len(payloads)} requests, concurrency {concurrency}", flush=True)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for index, _ in enumerate(pool.map(lambda p: client.predict(p, stats), payloads), start=1):
            if index % 100 == 0:
                print(f"    {index}/{len(payloads)} sent", flush=True)
    return stats


def send_for(
    client: ScoringClient,
    source: Iterator[Payload],
    concurrency: int,
    duration: float,
    stop: threading.Event | None = None,
    rate_per_worker: float = 0.0,
) -> RunStats:
    stats = RunStats()
    deadline = time.monotonic() + duration
    source_lock = threading.Lock()
    stop = stop or threading.Event()

    def worker() -> None:
        while time.monotonic() < deadline and not stop.is_set():
            with source_lock:
                payload = next(source)
            client.predict(payload, stats)
            if rate_per_worker > 0:
                time.sleep(1.0 / rate_per_worker)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return stats


def trigger_drift_analysis(drift_url: str, window: int) -> dict[str, Any] | None:
    try:
        response = requests.post(
            f"{drift_url.rstrip('/')}/analyze", json={"window_size": window, "save_report": True}, timeout=120
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"(drift monitor not reachable at {drift_url}: {type(exc).__name__})")
        return None
    result = response.json()
    if result.get("status") == "success":
        top = sorted((result.get("psi") or {}).items(), key=lambda kv: kv[1], reverse=True)[:3]
        print(
            f"==> drift analysis: drifted={result['is_drifted']} share={result['drift_share']:.2f} "
            f"prediction_psi={result.get('prediction_psi')} top_psi={[(k, round(v, 2)) for k, v in top]}"
        )
    else:
        print(f"==> drift analysis {result.get('status')}: {result.get('reason') or result.get('detail')}")
    return {
        k: result.get(k)
        for k in (
            "status",
            "is_drifted",
            "drift_share",
            "max_psi",
            "prediction_psi",
            "prediction_shift",
            "reasons",
            "report",
            "current_samples",
        )
    }


# --- scenarios ---------------------------------------------------------------------------------


def scenario_normal(args: argparse.Namespace, client: ScoringClient) -> dict[str, Any]:
    payloads = replay_payloads("stream_normal.csv")[: args.count]
    stats = send_all(client, payloads, args.concurrency, "normal replay (stream_normal.csv)")
    return {"traffic": stats.summary(), "drift": trigger_drift_analysis(args.drift_url, args.window)}


def scenario_drift(args: argparse.Namespace, client: ScoringClient) -> dict[str, Any]:
    replay = replay_payloads("stream_drifted.csv")[: int(args.count * 0.8)]
    personas = persona_payloads("campaign_drift", args.count - len(replay))
    payloads = replay + personas
    random.Random(7).shuffle(payloads)
    stats = send_all(client, payloads, args.concurrency, "Gen-Z campaign (stream_drifted.csv + campaign personas)")
    return {"traffic": stats.summary(), "drift": trigger_drift_analysis(args.drift_url, args.window)}


def scenario_attack(args: argparse.Namespace, client: ScoringClient) -> dict[str, Any]:
    payloads = persona_payloads("fraud_attack", args.count)
    stats = send_all(client, payloads, args.concurrency, "coordinated delinquency attack (fraud_attack personas)")
    return {"traffic": stats.summary(), "drift": trigger_drift_analysis(args.drift_url, args.window)}


def scenario_load(args: argparse.Namespace, client: ScoringClient) -> dict[str, Any]:
    print(f"==> load: {args.concurrency} workers for {args.duration:.0f}s (stream_normal.csv replay)", flush=True)
    started = time.monotonic()
    stats = send_for(client, cycle(replay_payloads("stream_normal.csv")), args.concurrency, args.duration)
    elapsed = time.monotonic() - started
    summary = stats.summary()
    summary["throughput_rps"] = round(summary["requests"] / elapsed, 1)
    print(
        f"    throughput {summary['throughput_rps']} req/s | latency {summary['latency_ms']} | "
        f"errors {summary['errors']}"
    )
    return {"traffic": summary, "duration_seconds": round(elapsed, 1)}


def scenario_outage(args: argparse.Namespace, client: ScoringClient) -> dict[str, Any]:
    compose = shlex.split(args.compose)
    stop = threading.Event()
    source = cycle(replay_payloads("stream_normal.csv"))
    total = args.down_seconds + args.recovery_timeout + 30
    holder: dict[str, RunStats] = {}
    traffic = threading.Thread(
        target=lambda: holder.update(stats=send_for(client, source, 2, total, stop, rate_per_worker=2.0)),
        daemon=True,
    )
    traffic.start()
    time.sleep(10)

    print(f"==> outage: stopping '{args.target}' for {args.down_seconds:.0f}s", flush=True)
    subprocess.run([*compose, "stop", args.target], check=True)
    stopped_at = time.monotonic()
    time.sleep(args.down_seconds)
    print(f"==> outage: starting '{args.target}'", flush=True)
    subprocess.run([*compose, "start", args.target], check=True)

    started_at = time.monotonic()
    recovered = None
    while time.monotonic() - started_at < args.recovery_timeout:
        if client.ready():
            recovered = round(time.monotonic() - started_at, 1)
            break
        time.sleep(1)
    print(f"==> recovery: {'ready after ' + str(recovered) + 's' if recovered is not None else 'NOT ready'}")
    time.sleep(10)
    stop.set()
    traffic.join()
    return {
        "target": args.target,
        "down_seconds": round(started_at - stopped_at, 1),
        "recovery_seconds": recovered,
        "traffic": holder["stats"].summary() if "stats" in holder else {},
    }


SCENARIOS: dict[str, Callable[[argparse.Namespace, ScoringClient], dict[str, Any]]] = {
    "normal": scenario_normal,
    "drift": scenario_drift,
    "attack": scenario_attack,
    "load": scenario_load,
    "outage": scenario_outage,
}

NEXT_STEPS = {
    "normal": "Drift gauges should return to 0; drift alerts resolve within ~2 min.",
    "drift": "DataDriftDetected fires after ~2 min (make alerts); `make drift-dag` triggers model_retrain. "
    "Resolve with `make simulate SCENARIO=normal`.",
    "attack": "Watch the Business dashboard (decline spike) and PredictionDistributionShift. "
    "Resolve with `make simulate SCENARIO=normal`.",
    "load": "Compare p95 with the 100 ms SLO on the Infra & SLA dashboard; "
    "with `make chaos-latency` HighLatencyP95 fires after ~2 min (`make chaos-restore`).",
    "outage": "APIDown fired while the API was stopped and resolves ~1 min after recovery.",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:18020"))
    parser.add_argument("--drift-url", default=os.getenv("DRIFT_MONITOR_URL", "http://localhost:18085"))
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--count", type=int, default=600, help="requests for normal/drift/attack (default 600)")
    parser.add_argument("--window", type=int, default=500, help="drift analysis window (default 500)")
    parser.add_argument(
        "--concurrency", type=int, default=None, help="workers (default 2, inside the p95 SLO; load: 32)"
    )
    parser.add_argument("--duration", type=float, default=180, help="load duration in seconds (default 180)")
    parser.add_argument("--target", default="api", help="outage: compose service to stop (default api)")
    parser.add_argument("--down-seconds", type=float, default=90, help="outage duration (default 90)")
    parser.add_argument("--recovery-timeout", type=float, default=180)
    parser.add_argument("--compose", default=None, help="compose command for outage (default: project compose)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if args.concurrency is None:
        args.concurrency = 32 if args.scenario == "load" else 2
    if args.compose is None:
        env_file = args.env_file if args.env_file.is_file() else PROJECT_ROOT / ".env.example"
        args.compose = (
            f"docker compose -f {PROJECT_ROOT / 'deploy/compose/docker-compose.yml'} " f"--env-file {env_file}"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    random.seed(args.seed)
    client = ScoringClient(args.api_url, resolve_api_key(read_env_file(args.env_file)))
    if args.scenario != "outage" and not client.ready():
        if not client.alive():
            print(f"API at {args.api_url} is not reachable (make up / make health).")
            return 1
        print(f"WARNING: API at {args.api_url} is alive but not ready; expect 5xx (chaos drill?).")

    started = datetime.now(UTC)
    result = SCENARIOS[args.scenario](args, client)
    report = {
        "scenario": args.scenario,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "api_url": args.api_url,
        **result,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{args.scenario}_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    traffic = result.get("traffic", {})
    print(
        f"\nSummary: {traffic.get('requests', 0)} requests, {traffic.get('errors', 0)} errors, "
        f"decisions {traffic.get('decision_share', {})}, latency {traffic.get('latency_ms', {})}"
    )
    print(f"Report: {path.relative_to(PROJECT_ROOT)}")
    print(f"Next: {NEXT_STEPS[args.scenario]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
