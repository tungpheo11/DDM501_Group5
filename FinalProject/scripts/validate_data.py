"""Entrypoint: validate every versioned dataset against its pandera contract.

Writes reports/data_validation.json and exits non-zero when any dataset fails.
"""

import json
import sys
from datetime import UTC, datetime

from credit_risk.config import get_logger, get_settings, setup_logging
from credit_risk.data.manifest import load_manifest, verify_file
from credit_risk.data.validation import validate_data_directory

if __name__ == "__main__":
    setup_logging()
    logger = get_logger(__name__)
    paths = get_settings().paths
    manifest = load_manifest(paths.data_manifest) if paths.data_manifest.exists() else {"files": []}

    reports = validate_data_directory(paths.data_dir)
    results = []
    for report in reports:
        entry = report.to_dict()
        entry["manifest_hash_match"] = verify_file(manifest, paths.data_dir, report.dataset)
        results.append(entry)
        status = "PASS" if report.passed and entry["manifest_hash_match"] else "FAIL"
        logger.info("%s %s rows=%d violations=%d", status, report.dataset, report.rows, report.total_failures)

    passed = all(r["passed"] and r["manifest_hash_match"] for r in results)
    output = paths.reports_dir / "data_validation.json"
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data_version": manifest.get("fingerprint"),
        "passed": passed,
        "datasets": results,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s", output)
    sys.exit(0 if passed else 1)
