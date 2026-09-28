"""Entrypoint: inspect the model registry, bootstrap/promote a version or roll back @champion."""

import argparse
import json

from credit_risk.config import setup_logging
from credit_risk.training.registry import (
    bootstrap_champion,
    describe_registry,
    promote_model_version,
    rollback_champion,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="List versions and aliases")
    sub.add_parser("bootstrap", help="Register the local champion artifact as @champion if the registry has none")
    promote = sub.add_parser("promote", help="Move @champion to a version")
    promote.add_argument("version")
    promote.add_argument("--reason", default="manual promotion")
    rollback = sub.add_parser("rollback", help="Move @champion back (default: @previous_champion)")
    rollback.add_argument("--to-version", default=None)
    args = parser.parse_args()

    setup_logging()
    if args.command == "promote":
        print(promote_model_version(args.version, reason=args.reason))
    elif args.command == "rollback":
        print(rollback_champion(to_version=args.to_version))
    elif args.command == "bootstrap":
        print(bootstrap_champion() or "champion already registered")
    print(json.dumps(describe_registry(), indent=2))
