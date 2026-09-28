#!/usr/bin/env python3
"""Script: run_fairness_audit.py
Executes comprehensive Responsible AI Fairness, Bias, and Explainability audit.
Wraps the enterprise Responsible AI pipeline in credit_risk.responsible_ai.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from credit_risk.responsible_ai.analysis import run_responsible_ai  # noqa: E402


def run_audit() -> None:
    """Executes the full Responsible AI audit and prints executive summary."""
    print("=" * 70)
    print("⚖️  RESPONSIBLE AI: FAIRNESS, BIAS & EXPLAINABILITY AUDIT")
    print("=" * 70)

    outcome = run_responsible_ai()
    fairness = outcome.fairness
    print("\n✓ Responsible AI audit generated successfully.")
    print(f"  • Champion Candidate: {fairness.get('model', {}).get('candidate', 'N/A')}")
    print(f"  • Overall Samples:    {fairness.get('overall', {}).get('rows', 0)}")
    print(f"  • Default Rate:       {fairness.get('overall', {}).get('default_rate', 0):.2%}")

    print("\n--- 1. Demographic Fairness Analysis (Four-Fifths Rule: 0.80 - 1.25) ---")
    audit_data = fairness.get("audit", {})
    for attr, metrics in audit_data.items():
        if isinstance(metrics, dict) and "disparate_impact_ratio" in metrics:
            dir_val = metrics["disparate_impact_ratio"]
            dpd_val = metrics.get("demographic_parity_difference", 0.0)
            status = "PASSED (No Bias)" if metrics.get("four_fifths_rule_passed", True) else "FLAGGED"
            print(f"  • {attr:20s}: DIR = {dir_val:.4f} | DPD = {dpd_val:.4f} | Status: {status}")

    print("\n✓ Reports written to:")
    for k, p in outcome.paths.items():
        print(f"  - {k}: {p}")


if __name__ == "__main__":
    run_audit()
