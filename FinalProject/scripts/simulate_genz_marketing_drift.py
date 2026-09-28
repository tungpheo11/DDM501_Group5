"""
Script: simulate_genz_marketing_drift.py
Convenience runner for viral Gen-Z acquisition marketing drift shock (PSI >= 0.25).
Referenced in proposal and presentation guides:
  python scripts/simulate_genz_marketing_drift.py --count 60
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulations.scenarios import GenZDriftScenario  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Simulate Gen-Z Acquisition Marketing Drift Shock")
    parser.add_argument("--api-url", default="http://localhost:18020/predict", help="Prediction endpoint URL")
    parser.add_argument("--count", type=int, default=60, help="Number of applications to simulate")
    parser.add_argument("--delay", type=float, default=0.02, help="Delay between applications (seconds)")
    args = parser.parse_args()

    print(f"🚨 Simulating Gen-Z drift shock to {args.api_url} ({args.count} requests)...")
    scenario = GenZDriftScenario(api_url=args.api_url)
    res = scenario.run(count=args.count, delay_sec=args.delay)
    print("\n--- RESULTS ---")
    for k, v in res.items():
        print(f"  {k:20s}: {v}")


if __name__ == "__main__":
    main()
