"""Entrypoint: fairness audit + mitigation, SHAP/LIME explanations, reports and doc blocks."""

import argparse
from pathlib import Path

from credit_risk.config import setup_logging
from credit_risk.responsible_ai.analysis import run_responsible_ai

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="Defaults to configs/responsible_ai.yaml")
    parser.add_argument("--no-docs", action="store_true", help="Do not refresh generated blocks in docs/")
    args = parser.parse_args()

    setup_logging()
    outcome = run_responsible_ai(config_path=args.config, sync_docs=not args.no_docs)

    for attribute, result in outcome.fairness["audit"].items():
        summary = result["summary"]
        print(
            f"{attribute:<10} DPD {summary['demographic_parity_difference']:.4f} "
            f"EOD {summary['equalized_odds_difference']:.4f} -> {result['status']}"
        )
    print(f"SHAP/LIME mean overlap@k: {outcome.explainability['mean_overlap_at_k']:.0%}")
    for name, path in outcome.paths.items():
        print(f"{name}: {path}")
    for path in outcome.synced_docs:
        print(f"doc refreshed: {path}")
