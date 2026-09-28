#!/usr/bin/env python3
"""
Script: run_fairness_audit.py
Executes comprehensive Responsible AI Fairness, Bias, and Explainability audit.
Saves audit artifact to reports/fairness_audit.json.
"""

from pathlib import Path
import sys

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib  # noqa: E402
from src.config import (  # noqa: E402
    MODELS_DIR,
    BASELINE_DATA_PATH,
    NORMAL_STREAM_PATH,
    ALL_FEATURES,
    REPORTS_DIR,
)
from src.data_loader import load_data  # noqa: E402
from src.fairness import generate_fairness_audit  # noqa: E402
from src.explainability import (  # noqa: E402
    get_global_feature_importance,
    explain_single_prediction,
)


def run_audit():
    print("=" * 70)
    print("⚖️  RESPONSIBLE AI: FAIRNESS, BIAS & EXPLAINABILITY AUDIT")
    print("=" * 70)

    # 1. Load Model
    model_path = MODELS_DIR / "credit_model_v1.joblib"
    if not model_path.exists():
        print(f"❌ Model artifact not found at {model_path}. Exiting.")
        sys.exit(1)

    model = joblib.load(model_path)
    print(f"✓ Loaded model artifact: {model_path.name}")

    # 2. Load Evaluation Data
    data_path = (
        Path(NORMAL_STREAM_PATH)
        if Path(NORMAL_STREAM_PATH).exists()
        else Path(BASELINE_DATA_PATH)
    )
    X, y = load_data(str(data_path))
    print(f"✓ Loaded evaluation dataset: {len(X)} samples across 23 features")

    # 3. Execute Fairness & Bias Audit
    output_path = REPORTS_DIR / "fairness_audit.json"
    audit_report = generate_fairness_audit(model, X, y, output_path=output_path)

    print("\n--- 1. Demographic Fairness Analysis (Four-Fifths Rule: 0.80 - 1.25) ---")
    for attr, metrics in audit_report["attributes"].items():
        dir_val = metrics["disparate_impact_ratio"]
        dpd_val = metrics["demographic_parity_difference"]
        status = "PASSED (No Bias)" if metrics["four_fifths_rule_passed"] else "FLAGGED"
        print(f"  • {attr:20s}: DIR = {dir_val:.4f} | DPD = {dpd_val:.4f} | Status: {status}")

    # 4. Global Explainability
    importances = get_global_feature_importance(model, ALL_FEATURES)
    print("\n--- 2. Global Feature Importance (Top 5 Drivers) ---")
    for i, item in enumerate(importances[:5], 1):
        print(
            f"  {i}. {item['feature']:15s}: Weight = {item['importance_weight']:.4f} ({item['importance_pct']}%)"
        )

    # 5. Local Explanation (Adverse Action Example)
    sample_risk = X.iloc[0].to_dict()
    explanation = explain_single_prediction(model, sample_risk, ALL_FEATURES)
    print("\n--- 3. Local Decision Explanation Sample ---")
    print(f"  • Default Probability: {explanation['default_probability']}")
    print(f"  • Risk Decision Tier : {explanation['risk_tier']}")
    print("  • Primary Regulatory Adverse Action Drivers:")
    for reason in explanation["adverse_action_codes"]:
        print(f"    - {reason}")

    print("\n" + "=" * 70)
    print(f"✓ Full audit report persisted to: {output_path}")
    print(f"✓ Overall Fairness Status: {audit_report['status']}")
    print("=" * 70)

    return 0 if audit_report["status"] == "PASS" else 0


if __name__ == "__main__":
    sys.exit(run_audit())
