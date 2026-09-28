"""Delete inference logs older than the retention window (privacy: storage limitation)."""

import argparse

from credit_risk.config import get_settings, setup_logging
from credit_risk.responsible_ai.privacy import DEFAULT_RETENTION_DAYS, purge_inference_logs
from credit_risk.serving import database

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--dry-run", action="store_true", help="Only count the rows that would be deleted")
    args = parser.parse_args()

    setup_logging()
    if not database.init_db(get_settings().database.url):
        raise SystemExit("Inference-log database unreachable")
    affected = purge_inference_logs(args.retention_days, dry_run=args.dry_run)
    verb = "would delete" if args.dry_run else "deleted"
    print(f"{verb} {affected} inference log(s) older than {args.retention_days} days")
