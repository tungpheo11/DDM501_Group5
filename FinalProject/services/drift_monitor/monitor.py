"""Drift monitor state: reference window, champion reference predictions, latest analysis.

Metric names are part of the monitoring contract (Grafana dashboards and alert
rules in ``monitoring/`` query them); rename only together with ``monitoring/``.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from prometheus_client import Counter, Gauge, Histogram

from credit_risk.config import Settings, get_logger
from credit_risk.data.schema import ALL_FEATURES
from credit_risk.monitoring.drift import (
    PROBABILITY_COLUMN,
    analyze_frames,
    load_recent_inference_logs,
    load_reference_features,
)
from credit_risk.utils.network import is_service_reachable

logger = get_logger("drift_monitor")

REPORT_NAME = re.compile(r"^drift_report_\d{8}T\d{6}Z\.html$")

DRIFT_DETECTED = Gauge("credit_drift_detected", "1 when the latest analysis declared drift, else 0")
DRIFT_SHARE = Gauge("credit_drift_share", "Share of feature columns flagged as drifted by Evidently")
DRIFTED_FEATURES = Gauge("credit_drift_drifted_features", "Number of feature columns flagged as drifted")
MAX_PSI = Gauge("credit_drift_max_psi", "Largest PSI across the monitored key features")
FEATURE_PSI = Gauge("credit_drift_feature_psi", "PSI of a key feature (current window vs reference)", ["feature"])
FEATURE_DRIFTED = Gauge("credit_drift_feature_drifted", "1 when Evidently flags the column as drifted", ["feature"])
FEATURE_SCORE = Gauge(
    "credit_drift_feature_score", "Evidently drift score (stattest statistic) per column", ["feature"]
)
PREDICTION_PSI = Gauge(
    "credit_drift_prediction_psi",
    "PSI of predicted default probabilities (current window vs champion on the reference)",
)
PREDICTION_SHIFT = Gauge(
    "credit_drift_prediction_shift", "1 when the prediction PSI reached the critical threshold, else 0"
)
CURRENT_SAMPLES = Gauge("credit_drift_current_samples", "Inference logs in the analysed window")
REFERENCE_SAMPLES = Gauge("credit_drift_reference_samples", "Reference rows used for the comparison")
LAST_ANALYSIS = Gauge(
    "credit_drift_last_analysis_timestamp_seconds", "Unix time of the latest completed (non-skipped) analysis"
)
REFERENCE_MODEL = Gauge(
    "credit_drift_reference_model_info",
    "Model that scored the reference window (value is always 1)",
    ["model_version", "source"],
)
ANALYSES = Counter("credit_drift_analyses_total", "Drift analyses by outcome", ["result"])
ANALYSIS_DURATION = Histogram(
    "credit_drift_analysis_duration_seconds",
    "Duration of one drift analysis",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

LogLoader = Callable[[Settings, int], pd.DataFrame | None]
ModelLoader = Callable[[Settings], tuple[Any | None, str, str]]


def default_log_loader(settings: Settings, limit: int) -> pd.DataFrame | None:
    """Most recent inference logs from the configured database."""
    return load_recent_inference_logs(settings, limit=limit)


def default_model_loader(settings: Settings) -> tuple[Any | None, str, str]:
    """Champion from the MLflow registry, else the local fallback artifact.

    Returns:
        ``(model_or_None, version_label, source)``.
    """
    tracking_uri = settings.mlflow.tracking_uri
    if is_service_reachable(tracking_uri, timeout=settings.serving.mlflow_probe_timeout_seconds):
        try:
            from credit_risk.training.registry import get_alias_version, get_registry_client, load_model_by_alias

            model = load_model_by_alias(settings=settings)
            client = get_registry_client(settings)
            if model is not None and client is not None:
                version = get_alias_version(client, settings.mlflow.model_name, settings.mlflow.model_alias)
                return model, str(version), "mlflow_registry"
        except Exception as exc:  # Any registry/artifact failure falls back to the local artifact.
            logger.warning("Could not load the registry champion (%s); using the local artifact.", exc)

    import joblib

    artifact = settings.paths.models_dir / settings.serving.fallback_model_artifact
    if not artifact.exists():
        return None, "none", "unavailable"
    return joblib.load(artifact), artifact.stem, "local_artifact"


def _positive_class_probabilities(model: Any, frame: pd.DataFrame) -> pd.Series:
    names = getattr(model, "feature_names_in_", None)
    features = frame[list(names)] if names is not None else frame
    proba = model.predict_proba(features)
    classes = list(getattr(model, "classes_", [0, 1]))
    column = classes.index(1) if 1 in classes else proba.shape[1] - 1
    return pd.Series(proba[:, column], index=frame.index, dtype=float)


@dataclass
class ReferenceState:
    """Reference window and the champion predictions on it."""

    features: pd.DataFrame
    predictions: pd.Series | None
    model_version: str
    model_source: str
    loaded_at: datetime


class DriftMonitor:
    """Runs drift analyses and publishes the ``credit_drift_*`` metrics."""

    def __init__(
        self,
        settings: Settings,
        *,
        log_loader: LogLoader = default_log_loader,
        model_loader: ModelLoader = default_model_loader,
    ) -> None:
        self.settings = settings
        self._log_loader = log_loader
        self._model_loader = model_loader
        self._lock = threading.Lock()
        self.reference: ReferenceState | None = None
        self.latest: dict[str, Any] | None = None
        self.reports_dir: Path = settings.paths.reports_dir / "drift"
        self._reset_gauges()

    @staticmethod
    def _reset_gauges() -> None:
        gauges = (
            DRIFT_DETECTED,
            DRIFT_SHARE,
            DRIFTED_FEATURES,
            MAX_PSI,
            PREDICTION_PSI,
            PREDICTION_SHIFT,
            CURRENT_SAMPLES,
        )
        for gauge in gauges:
            gauge.set(0)

    def load_reference(self) -> ReferenceState:
        """(Re)load the reference sample and score it with the current champion."""
        cfg = self.settings
        reference = load_reference_features(cfg)
        reference = reference[[c for c in ALL_FEATURES if c in reference.columns]]
        if len(reference) > cfg.drift.reference_sample_size:
            reference = reference.sample(cfg.drift.reference_sample_size, random_state=cfg.training.random_state)
        reference = reference.reset_index(drop=True)
        model, version, source = self._model_loader(cfg)
        predictions = _positive_class_probabilities(model, reference) if model is not None else None
        state = ReferenceState(reference, predictions, version, source, datetime.now(UTC))
        with self._lock:
            self.reference = state
        REFERENCE_SAMPLES.set(len(state.features))
        REFERENCE_MODEL.clear()
        REFERENCE_MODEL.labels(model_version=version, source=source).set(1)
        logger.info("Reference loaded: %d rows scored by %s (%s)", len(state.features), version, source)
        return state

    def analyze(self, window_size: int | None = None, save_report: bool = False) -> dict[str, Any]:
        """Compare the latest ``window_size`` inference logs with the reference.

        Returns ``status="skipped"`` (never raises) when the database is unavailable or
        the window is smaller than ``drift.min_current_samples``.
        """
        cfg = self.settings
        window = int(window_size or cfg.drift.window_size)
        reference = self.reference or self.load_reference()
        started = time.perf_counter()

        logs = self._log_loader(cfg, window)
        if logs is None:
            return self._skipped("database_unavailable", 0, window)
        CURRENT_SAMPLES.set(len(logs))
        if len(logs) < cfg.drift.min_current_samples:
            return self._skipped("insufficient_samples", len(logs), window)

        current_predictions = logs[PROBABILITY_COLUMN] if PROBABILITY_COLUMN in logs.columns else None
        try:
            analysis, report = analyze_frames(
                reference.features,
                logs.drop(columns=[PROBABILITY_COLUMN], errors="ignore"),
                cfg.drift,
                reference_predictions=reference.predictions,
                current_predictions=current_predictions,
            )
        except Exception as exc:  # A malformed window must not kill the background loop.
            ANALYSES.labels(result="error").inc()
            logger.exception("Drift analysis failed")
            return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"[:300], "window_size": window}

        duration = time.perf_counter() - started
        ANALYSIS_DURATION.observe(duration)
        ANALYSES.labels(result="success").inc()
        self._publish(analysis.as_dict())
        result: dict[str, Any] = {
            "status": "success",
            "analyzed_at": datetime.now(UTC).isoformat(),
            "window_size": window,
            "duration_seconds": round(duration, 3),
            "reference_model_version": reference.model_version,
            "reference_model_source": reference.model_source,
            **analysis.as_dict(),
        }
        if save_report:
            result["report"] = self._save_report(report)
        with self._lock:
            self.latest = result
        logger.info(
            "Drift analysis: drifted=%s share=%.2f max_psi=%.3f prediction_psi=%s (%d samples)",
            analysis.is_drifted,
            analysis.drift_share,
            analysis.max_psi,
            analysis.prediction_psi,
            analysis.current_samples,
            extra={"event": "drift_analysis", "is_drifted": analysis.is_drifted},
        )
        return result

    def _skipped(self, reason: str, samples: int, window: int) -> dict[str, Any]:
        ANALYSES.labels(result="skipped").inc()
        result = {
            "status": "skipped",
            "reason": reason,
            "current_samples": samples,
            "min_samples": self.settings.drift.min_current_samples,
            "window_size": window,
            "is_drifted": False,
        }
        logger.info("Drift analysis skipped: %s (%d samples)", reason, samples)
        return result

    @staticmethod
    def _publish(summary: dict[str, Any]) -> None:
        DRIFT_DETECTED.set(1 if summary["is_drifted"] else 0)
        DRIFT_SHARE.set(summary["drift_share"])
        DRIFTED_FEATURES.set(len(summary["drifted_columns"]))
        MAX_PSI.set(summary["max_psi"])
        PREDICTION_PSI.set(summary["prediction_psi"] or 0.0)
        PREDICTION_SHIFT.set(1 if summary["prediction_shift"] else 0)
        CURRENT_SAMPLES.set(summary["current_samples"])
        LAST_ANALYSIS.set(time.time())
        FEATURE_PSI.clear()
        for feature, value in summary["psi"].items():
            FEATURE_PSI.labels(feature=feature).set(value)
        FEATURE_DRIFTED.clear()
        FEATURE_SCORE.clear()
        drifted = set(summary["drifted_columns"])
        for feature, score in summary["column_scores"].items():
            FEATURE_DRIFTED.labels(feature=feature).set(1 if feature in drifted else 0)
            FEATURE_SCORE.labels(feature=feature).set(score)

    def _save_report(self, report: Any) -> str:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        name = f"drift_report_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.html"
        report.save_html(str(self.reports_dir / name))
        reports = sorted(self.reports_dir.glob("drift_report_*.html"))
        for stale in reports[: max(0, len(reports) - self.settings.drift.max_saved_reports)]:
            stale.unlink(missing_ok=True)
        return name

    def list_reports(self) -> list[dict[str, Any]]:
        """Saved HTML reports, newest first."""
        if not self.reports_dir.exists():
            return []
        return [
            {
                "name": path.name,
                "size_kb": round(path.stat().st_size / 1024, 1),
                "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "url": f"/reports/{path.name}",
            }
            for path in sorted(self.reports_dir.glob("drift_report_*.html"), reverse=True)
        ]

    def report_path(self, name: str) -> Path | None:
        """Path of a saved report; ``None`` for unknown or malformed names (no path traversal)."""
        if not REPORT_NAME.match(name):
            return None
        path = self.reports_dir / name
        return path if path.is_file() else None
