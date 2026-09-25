"""
Script: detect_drift.py
Uses Evidently AI to detect Data Drift between the Baseline training distribution
and the production inference stream (queried from PostgreSQL or stream_drifted.csv).
Generates an interactive HTML report and a JSON summary.
"""

import os
import json
import pandas as pd
from sqlalchemy import create_engine

from evidently.legacy.report import Report
from evidently.legacy.metric_preset import DataDriftPreset, DataQualityPreset

from src.config import (

    BASELINE_DATA_PATH,
    DRIFTED_STREAM_PATH,
    DATABASE_URL,
    REPORTS_DIR,
)


def load_inference_stream_from_db():
    """Attempts to load recent inference features from PostgreSQL inference_logs."""
    try:
        engine = create_engine(DATABASE_URL)
        query = "SELECT features_json FROM inference_logs ORDER BY id DESC LIMIT 5000;"
        df_logs = pd.read_sql(query, engine)
        if len(df_logs) >= 50:
            print(f"Loaded {len(df_logs)} inference records from PostgreSQL.")
            # features is stored as JSON
            features_list = [
                row if isinstance(row, dict) else json.loads(row)
                for row in df_logs["features_json"]
            ]
            return pd.DataFrame(features_list)

    except Exception as exc:
        print(f"Database query note: {exc}. Using fallback stream file.")
    return None


def calculate_psi(expected: pd.Series, actual: pd.Series, num_buckets: int = 10) -> float:
    """Calculates Population Stability Index (PSI) between reference and current series."""
    import numpy as np

    # Quantile binning on reference
    try:
        quantiles = np.linspace(0, 1, num_buckets + 1)
        bins = np.percentile(expected.dropna(), quantiles * 100)
        bins[0] -= 1e-5
        bins[-1] += 1e-5
        bins = np.unique(bins)

        if len(bins) < 2:
            return 0.0

        exp_counts, _ = np.histogram(expected.dropna(), bins=bins)
        act_counts, _ = np.histogram(actual.dropna(), bins=bins)

        # Avoid zero division with smoothing
        exp_pct = (exp_counts + 1e-4) / (len(expected) + 1e-4 * len(exp_counts))
        act_pct = (act_counts + 1e-4) / (len(actual) + 1e-4 * len(act_counts))

        psi_val = np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct))
        return float(psi_val)
    except Exception:
        return 0.0


def run_drift_analysis():
    print("=" * 65)
    print("Running Evidently AI Data Drift & Covariate Drift Analysis")
    print("=" * 65)

    os.makedirs(REPORTS_DIR, exist_ok=True)

    # 1. Load Reference (Baseline) Data
    if not os.path.exists(BASELINE_DATA_PATH):
        raise FileNotFoundError(f"Baseline data not found at {BASELINE_DATA_PATH}")

    ref_df = pd.read_csv(BASELINE_DATA_PATH)
    if "default_payment_next_month" in ref_df.columns:
        ref_features = ref_df.drop(columns=["default_payment_next_month"])
    else:
        ref_features = ref_df.copy()

    # 2. Load Current (Production / Stream) Data
    cur_features = load_inference_stream_from_db()
    if cur_features is None or len(cur_features) < 50:
        if os.path.exists(DRIFTED_STREAM_PATH):
            print(f"Loading drifted stream from: {DRIFTED_STREAM_PATH}")
            cur_features = pd.read_csv(DRIFTED_STREAM_PATH)
            if "request_id" in cur_features.columns:
                cur_features = cur_features.drop(columns=["request_id"])
        else:
            raise FileNotFoundError("No production stream data available.")

    # Align columns
    common_cols = [c for c in ref_features.columns if c in cur_features.columns]
    ref_eval = ref_features[common_cols].dropna()
    cur_eval = cur_features[common_cols].dropna()

    print(f"Reference samples: {len(ref_eval)} | Current stream samples: {len(cur_eval)}")
    print(f"Features analyzed: {len(common_cols)}")

    # 3. Calculate PSI on key features
    key_features = ["AGE", "LIMIT_BAL", "PAY_0", "BILL_AMT1"]
    psi_results = {}
    for col in key_features:
        if col in common_cols:
            psi_val = calculate_psi(ref_eval[col], cur_eval[col])
            psi_results[col] = round(psi_val, 4)

    print("\n--- Population Stability Index (PSI) Summary ---")
    for col, val in psi_results.items():
        if val >= 0.25:
            status = "CRITICAL DRIFT (>=0.25)"
        elif val >= 0.10:
            status = "MODERATE (>=0.10)"
        else:
            status = "STABLE (<0.10)"
        print(f"  {col:12s}: PSI = {val:.4f} -> {status}")

    # 4. Generate Evidently HTML Report

    print("\nGenerating Evidently Data Drift & Quality Report...")
    drift_report = Report(metrics=[DataDriftPreset(), DataQualityPreset()])
    drift_report.run(reference_data=ref_eval, current_data=cur_eval)

    report_html_path = os.path.join(REPORTS_DIR, "drift_report.html")
    drift_report.save_html(report_html_path)

    print(f"Evidently HTML Report saved to: {report_html_path}")

    # Extract JSON metrics from report
    report_dict = drift_report.as_dict()
    summary_path = os.path.join(REPORTS_DIR, "drift_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "psi_metrics": psi_results,
            "drift_report": report_dict,
        }, f, indent=2, default=str)
    print(f"Drift summary JSON saved to: {summary_path}")

    # Check alert condition

    age_psi = psi_results.get("AGE", 0.0)
    is_drifted = age_psi >= 0.25 or any(v >= 0.25 for v in psi_results.values())
    if is_drifted:
        print("\n[ALERT] SIGNIFICANT DRIFT DETECTED!")
        print("Demographic shift identified in AGE and LIMIT_BAL.")
        print("Automatic trigger condition MET -> Initiating Retraining Loop.")
    else:
        print("\n[STATUS] Data distribution is within normal operating bounds.")

    return is_drifted, psi_results


if __name__ == "__main__":
    run_drift_analysis()
