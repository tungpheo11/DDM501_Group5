"""Data drift detection with PSI and Evidently.

Compares the baseline training distribution with the production stream (read
from the PostgreSQL ``inference_logs`` table, or the offline drifted stream file
as a fallback). :func:`analyze_frames` is the pure computation shared by the
offline report (:func:`run_drift_analysis`) and the online drift-monitor service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from credit_risk.config import Settings, get_logger, get_settings
from credit_risk.config.settings import DriftSettings
from credit_risk.data.schema import ALL_FEATURES, REQUEST_ID_COLUMN, TARGET_COLUMN

logger = get_logger(__name__)

PROBABILITY_COLUMN = "probability"


@dataclass(frozen=True)
class DriftResult:
    """Outcome of one offline drift analysis."""

    is_drifted: bool
    psi: dict[str, float]


@dataclass(frozen=True)
class DriftAnalysis:
    """Feature and prediction drift between a reference and a current window."""

    psi: dict[str, float]
    drift_share: float
    dataset_drift: bool
    drifted_columns: tuple[str, ...]
    column_scores: dict[str, float]
    reference_samples: int
    current_samples: int
    is_drifted: bool
    prediction_psi: float | None = None
    prediction_shift: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def max_psi(self) -> float:
        """Largest PSI across the monitored key features (0.0 when none were computed)."""
        return max(self.psi.values(), default=0.0)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable summary."""
        return {
            "is_drifted": self.is_drifted,
            "reasons": list(self.reasons),
            "psi": self.psi,
            "max_psi": self.max_psi,
            "drift_share": self.drift_share,
            "dataset_drift": self.dataset_drift,
            "drifted_columns": list(self.drifted_columns),
            "column_scores": self.column_scores,
            "prediction_psi": self.prediction_psi,
            "prediction_shift": self.prediction_shift,
            "reference_samples": self.reference_samples,
            "current_samples": self.current_samples,
        }


def calculate_psi(expected: pd.Series, actual: pd.Series, num_buckets: int = 10) -> float:
    """Population Stability Index of ``actual`` against quantile bins of ``expected``.

    Returns 0.0 when the reference has too few distinct values to bin.
    """
    expected_clean = expected.dropna()
    actual_clean = actual.dropna()
    if expected_clean.empty or actual_clean.empty:
        return 0.0

    quantiles = np.linspace(0, 1, num_buckets + 1)
    bins = np.percentile(expected_clean, quantiles * 100)
    bins[0] -= 1e-5
    bins[-1] += 1e-5
    bins = np.unique(bins)
    if len(bins) < 2:
        return 0.0

    exp_counts, _ = np.histogram(expected_clean, bins=bins)
    act_counts, _ = np.histogram(actual_clean, bins=bins)

    # Additive smoothing keeps log() finite for empty buckets.
    exp_pct = (exp_counts + 1e-4) / (len(expected) + 1e-4 * len(exp_counts))
    act_pct = (act_counts + 1e-4) / (len(actual) + 1e-4 * len(act_counts))
    return float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))


def classify_psi(value: float, moderate: float = 0.10, critical: float = 0.25) -> str:
    """Map a PSI value to ``STABLE`` / ``MODERATE`` / ``CRITICAL``."""
    if value >= critical:
        return "CRITICAL"
    if value >= moderate:
        return "MODERATE"
    return "STABLE"


def extract_evidently_drift(report_dict: dict[str, Any]) -> tuple[float, bool, tuple[str, ...], dict[str, float]]:
    """Pull ``(drift_share, dataset_drift, drifted_columns, column_scores)`` out of a legacy report dict."""
    share, dataset_drift = 0.0, False
    drifted: list[str] = []
    scores: dict[str, float] = {}
    for metric in report_dict.get("metrics", []):
        result = metric.get("result", {}) or {}
        if metric.get("metric") == "DatasetDriftMetric":
            share = float(result.get("share_of_drifted_columns", 0.0) or 0.0)
            dataset_drift = bool(result.get("dataset_drift", False))
        for column, info in (result.get("drift_by_columns") or {}).items():
            scores[column] = round(float(info.get("drift_score", 0.0) or 0.0), 6)
            if info.get("drift_detected") and column not in drifted:
                drifted.append(column)
    return share, dataset_drift, tuple(drifted), scores


def analyze_frames(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    drift_cfg: DriftSettings,
    *,
    include_quality: bool = False,
    reference_predictions: pd.Series | None = None,
    current_predictions: pd.Series | None = None,
) -> tuple[DriftAnalysis, Any]:
    """Compute PSI on key features, Evidently column drift and (optionally) prediction PSI.

    Feature drift (``is_drifted``) is declared when a key feature's PSI reaches
    ``critical_threshold`` or the share of Evidently-drifted columns reaches
    ``drift_share_threshold``. A prediction PSI at or above ``critical_threshold`` sets
    ``prediction_shift`` independently.

    Returns:
        ``(analysis, evidently_report)``; the report can be saved as HTML by the caller.

    Raises:
        ValueError: when the frames share no feature column or ``current`` is empty.
    """
    from evidently.legacy.metric_preset import DataDriftPreset, DataQualityPreset
    from evidently.legacy.report import Report

    common_cols = [c for c in reference.columns if c in current.columns and c in ALL_FEATURES]
    if not common_cols:
        raise ValueError("Reference and current data share no feature column.")
    ref_eval = reference[common_cols].dropna()
    cur_eval = current[common_cols].dropna()
    if cur_eval.empty:
        raise ValueError("Current window is empty.")

    psi = {
        col: round(calculate_psi(ref_eval[col], cur_eval[col], drift_cfg.num_buckets), 4)
        for col in drift_cfg.key_features
        if col in common_cols
    }

    metrics: list[Any] = [DataDriftPreset()]
    if include_quality:
        metrics.append(DataQualityPreset())
    report = Report(metrics=metrics)
    report.run(reference_data=ref_eval, current_data=cur_eval)
    share, dataset_drift, drifted, scores = extract_evidently_drift(report.as_dict())

    prediction_psi: float | None = None
    if reference_predictions is not None and current_predictions is not None and len(current_predictions) > 0:
        prediction_psi = round(calculate_psi(reference_predictions, current_predictions, drift_cfg.num_buckets), 4)

    reasons: list[str] = []
    critical = [col for col, value in psi.items() if value >= drift_cfg.critical_threshold]
    if critical:
        reasons.append(f"psi_critical:{','.join(critical)}")
    if share >= drift_cfg.drift_share_threshold:
        reasons.append(f"drift_share:{share:.2f}")
    is_drifted = bool(reasons)
    prediction_shift = prediction_psi is not None and prediction_psi >= drift_cfg.critical_threshold
    if prediction_shift:
        reasons.append(f"prediction_psi:{prediction_psi:.2f}")

    analysis = DriftAnalysis(
        psi=psi,
        drift_share=round(share, 4),
        dataset_drift=dataset_drift,
        drifted_columns=drifted,
        column_scores=scores,
        reference_samples=len(ref_eval),
        current_samples=len(cur_eval),
        is_drifted=is_drifted,
        prediction_psi=prediction_psi,
        prediction_shift=prediction_shift,
        reasons=tuple(reasons),
    )
    return analysis, report


def load_recent_inference_logs(settings: Settings | None = None, limit: int | None = None) -> pd.DataFrame | None:
    """Most recent logged inferences as features + ``probability`` (newest last), or ``None`` if unavailable."""
    cfg = settings or get_settings()
    row_limit = int(limit if limit is not None else cfg.drift.db_query_limit)
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(cfg.database.url)
        query = text("SELECT features_json, probability FROM inference_logs ORDER BY id DESC LIMIT :limit")
        df_logs = pd.read_sql(query, engine, params={"limit": row_limit})
        engine.dispose()
    except Exception as exc:  # DB driver errors vary by backend; callers decide on a fallback.
        logger.info("Inference log query unavailable (%s).", exc)
        return None

    if df_logs.empty:
        return pd.DataFrame(columns=[*ALL_FEATURES, PROBABILITY_COLUMN])
    rows = [row if isinstance(row, dict) else json.loads(row) for row in df_logs["features_json"]]
    frame = pd.DataFrame(rows)
    frame[PROBABILITY_COLUMN] = df_logs["probability"].astype(float).to_numpy()
    return frame.iloc[::-1].reset_index(drop=True)


def load_inference_stream_from_db(settings: Settings | None = None) -> pd.DataFrame | None:
    """Load the most recent logged inference features, or ``None`` if unavailable/too few."""
    cfg = settings or get_settings()
    frame = load_recent_inference_logs(cfg)
    if frame is None or len(frame) < cfg.drift.min_current_samples:
        return None
    logger.info("Loaded %d inference records from the database.", len(frame))
    return frame.drop(columns=[PROBABILITY_COLUMN])


def load_reference_features(settings: Settings | None = None) -> pd.DataFrame:
    """Baseline training features (target dropped).

    Raises:
        FileNotFoundError: when the baseline file is missing.
    """
    cfg = settings or get_settings()
    if not cfg.paths.baseline_data.exists():
        raise FileNotFoundError(f"Baseline data not found at {cfg.paths.baseline_data}")
    return pd.read_csv(cfg.paths.baseline_data).drop(columns=[TARGET_COLUMN], errors="ignore")


def _load_current_features(cfg: Settings) -> pd.DataFrame:
    current = load_inference_stream_from_db(cfg)
    if current is not None:
        return current
    stream_path = cfg.paths.drifted_stream
    if not stream_path.exists():
        raise FileNotFoundError("No production stream data available.")
    logger.info("Loading drifted stream from %s", stream_path)
    current = pd.read_csv(stream_path)
    return current.drop(columns=[REQUEST_ID_COLUMN], errors="ignore")


def run_drift_analysis(settings: Settings | None = None) -> DriftResult:
    """Run PSI + Evidently drift analysis and write the report artifacts."""
    cfg = settings or get_settings()
    drift_cfg = cfg.drift
    cfg.paths.reports_dir.mkdir(parents=True, exist_ok=True)

    reference = load_reference_features(cfg)
    current = _load_current_features(cfg)
    analysis, report = analyze_frames(reference, current, drift_cfg, include_quality=True)
    logger.info(
        "Reference samples: %d | current samples: %d | drifted columns: %d (share %.2f)",
        analysis.reference_samples,
        analysis.current_samples,
        len(analysis.drifted_columns),
        analysis.drift_share,
    )
    for col, value in analysis.psi.items():
        status = classify_psi(value, drift_cfg.moderate_threshold, drift_cfg.critical_threshold)
        logger.info("PSI %-12s = %.4f -> %s", col, value, status)

    html_path = cfg.paths.reports_dir / drift_cfg.report_html
    report.save_html(str(html_path))
    logger.info("Evidently HTML report saved to %s", html_path)

    summary_path = cfg.paths.reports_dir / drift_cfg.summary_json
    summary = {"psi_metrics": analysis.psi, "analysis": analysis.as_dict(), "drift_report": report.as_dict()}
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    logger.info("Drift summary JSON saved to %s", summary_path)

    is_drifted = any(value >= drift_cfg.critical_threshold for value in analysis.psi.values())
    if is_drifted:
        logger.warning("SIGNIFICANT DRIFT DETECTED: retraining trigger condition met.")
    else:
        logger.info("Data distribution is within normal operating bounds.")
    return DriftResult(is_drifted=is_drifted, psi=analysis.psi)
