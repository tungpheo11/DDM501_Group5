"""Prometheus metrics exported by the scoring API.

Metric names are part of the monitoring contract (Grafana dashboards and alert
rules query them); rename only together with ``monitoring/``.

Under gunicorn every worker writes its values to ``PROMETHEUS_MULTIPROC_DIR``
(see :mod:`credit_risk.monitoring.multiprocess`). Counters and histograms are
summed across workers; each gauge declares how worker values are combined
(``multiprocess_mode``, ignored in single-process mode).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field

from prometheus_client import Counter, Gauge, Histogram

from credit_risk.monitoring.multiprocess import multiprocess_dir

PREDICTION_REQUESTS = Counter(
    "credit_prediction_requests_total",
    "Total credit prediction requests received",
    ["decision", "status"],
)
PREDICTION_LATENCY = Histogram(
    "credit_prediction_duration_seconds",
    "Prediction execution latency in seconds",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
# Rolling gauges are per-worker windows; the most recently updated worker wins.
DEFAULT_RISK_RATIO = Gauge(
    "credit_default_prediction_ratio",
    "Rolling ratio of requests predicted as default risk (1)",
    multiprocess_mode="livemostrecent",
)
CREDIT_APPROVED_VOLUME = Counter(
    "credit_approved_volume_ntd_total",
    "Cumulative credit amount approved in NTD",
)
CREDIT_DECLINED_VOLUME = Counter(
    "credit_declined_volume_ntd_total",
    "Cumulative credit exposure blocked in NTD",
)
EXPECTED_LOSS = Counter(
    "credit_expected_loss_ntd_total",
    "Expected credit loss PD x exposure x LGD in NTD (DECLINE = loss avoided on the requested limit)",
    ["decision"],
)
AVG_AGE_GAUGE = Gauge(
    "credit_customer_age_rolling_mean",
    "Rolling mean age of incoming applicants",
    multiprocess_mode="livemostrecent",
)
AVG_LIMIT_GAUGE = Gauge(
    "credit_customer_limit_bal_rolling_mean",
    "Rolling mean credit limit of applicants in NTD",
    multiprocess_mode="livemostrecent",
)
AVG_UTILIZATION_GAUGE = Gauge(
    "credit_customer_utilization_ratio_mean",
    "Rolling credit card utilization ratio (BILL_AMT1 / LIMIT_BAL)",
    multiprocess_mode="livemostrecent",
)
PAY_0_DELAY_RATIO = Gauge(
    "credit_customer_pay_0_delayed_ratio",
    "Ratio of applicants with recent payment delay (PAY_0 > 0)",
    multiprocess_mode="livemostrecent",
)
CREDIT_SCORE_HISTOGRAM = Histogram(
    "credit_applicant_score_distribution",
    "Credit score distribution on 300-850 scale",
    buckets=[350, 450, 550, 650, 700, 750, 800, 850],
)
DEFAULT_PROBABILITY_HISTOGRAM = Histogram(
    "credit_prediction_default_probability",
    "Distribution of predicted default probabilities",
    buckets=[0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
BATCH_SIZE_HISTOGRAM = Histogram(
    "credit_prediction_batch_size",
    "Number of applicants per batch prediction request",
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
)

# --- HTTP layer (recorded by the request middleware for every route) --------
HTTP_REQUESTS = Counter(
    "credit_api_requests_total",
    "HTTP requests handled by the scoring API",
    ["method", "endpoint", "status"],
)
HTTP_LATENCY = Histogram(
    "credit_api_request_duration_seconds",
    "End-to-end HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0, 2.5],
)
AUTH_FAILURES = Counter(
    "credit_api_auth_failures_total",
    "Rejected API-key authentications",
    ["reason"],
)

# --- Served model state ------------------------------------------------------
# Worker modes: an identity is exposed while any worker serves it (retired identities
# are zeroed, then dropped at exposition); "loaded" needs every worker to have a
# model; "degraded" fires when any worker is on the fallback.
MODEL_INFO = Gauge(
    "credit_model_info",
    "Model currently served (value is always 1; identity lives in the labels)",
    ["model_name", "model_version", "source"],
    multiprocess_mode="livemax",
)
MODEL_LOADED = Gauge(
    "credit_model_loaded",
    "1 when a model is loaded and able to score, else 0",
    multiprocess_mode="livemin",
)
MODEL_DEGRADED = Gauge(
    "credit_model_degraded",
    "1 when serving the local fallback artifact instead of the MLflow registry model",
    multiprocess_mode="livemax",
)
MODEL_RELOADS = Counter("credit_model_reloads_total", "Model (re)load attempts", ["result"])

_model_state_lock = threading.Lock()


def _retire_model_info(keep: dict[str, str] | None = None) -> None:
    # Multiprocess files cannot drop a series, so retired identities are set to 0
    # (and filtered out at exposition); single-process mode removes them.
    for family in MODEL_INFO.collect():
        for sample in family.samples:
            if sample.labels != keep and sample.value:
                MODEL_INFO.labels(**sample.labels).set(0)
    if multiprocess_dir() is None:
        MODEL_INFO.clear()


def set_served_model(model_name: str, model_version: str, source: str, *, degraded: bool) -> None:
    """Publish the identity of the served model; retires the previous identity series."""
    labels = {"model_name": model_name, "model_version": model_version, "source": source}
    with _model_state_lock:
        _retire_model_info(keep=labels)
        MODEL_INFO.labels(**labels).set(1)
        MODEL_LOADED.set(1)
        MODEL_DEGRADED.set(1 if degraded else 0)


def set_model_unavailable() -> None:
    """Publish that no model can serve traffic."""
    with _model_state_lock:
        _retire_model_info()
        MODEL_LOADED.set(0)
        MODEL_DEGRADED.set(1)


def _mean(values: deque[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass
class RollingFeatureStats:
    """Fixed-size window over recent requests feeding the rolling gauges."""

    window: int = 200
    predictions: deque[float] = field(init=False)
    ages: deque[float] = field(init=False)
    limits: deque[float] = field(init=False)
    utilizations: deque[float] = field(init=False)
    delays: deque[float] = field(init=False)

    def __post_init__(self) -> None:
        self.predictions = deque(maxlen=self.window)
        self.ages = deque(maxlen=self.window)
        self.limits = deque(maxlen=self.window)
        self.utilizations = deque(maxlen=self.window)
        self.delays = deque(maxlen=self.window)

    def observe(self, prediction: int, age: int, limit_bal: float, utilization: float, pay_0: int) -> None:
        """Record one request and refresh the rolling gauges."""
        self.predictions.append(float(prediction))
        self.ages.append(float(age))
        self.limits.append(limit_bal)
        self.utilizations.append(utilization)
        self.delays.append(1.0 if pay_0 > 0 else 0.0)

        DEFAULT_RISK_RATIO.set(_mean(self.predictions))
        AVG_AGE_GAUGE.set(_mean(self.ages))
        AVG_LIMIT_GAUGE.set(_mean(self.limits))
        AVG_UTILIZATION_GAUGE.set(_mean(self.utilizations))
        PAY_0_DELAY_RATIO.set(_mean(self.delays))


def record_business_outcome(
    decision: str,
    credit_score: int,
    recommended_limit: float,
    limit_bal: float,
    probability: float | None = None,
    loss_given_default: float = 0.45,
) -> None:
    """Update decision counters, score/probability histograms, credit volume and expected-loss counters."""
    PREDICTION_REQUESTS.labels(decision=decision, status="200").inc()
    CREDIT_SCORE_HISTOGRAM.observe(credit_score)
    if probability is not None:
        DEFAULT_PROBABILITY_HISTOGRAM.observe(probability)
        exposure = recommended_limit if recommended_limit > 0 else limit_bal
        EXPECTED_LOSS.labels(decision=decision).inc(probability * exposure * loss_given_default)
    if decision == "APPROVE":
        CREDIT_APPROVED_VOLUME.inc(recommended_limit)
    elif decision == "DECLINE":
        CREDIT_DECLINED_VOLUME.inc(limit_bal)
