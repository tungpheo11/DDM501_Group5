"""Entrypoint: regenerate data/manifest.json (hashes, shapes) after any data change."""

from credit_risk.config import get_logger, get_settings, setup_logging
from credit_risk.data.manifest import write_manifest

if __name__ == "__main__":
    setup_logging()
    paths = get_settings().paths
    manifest = write_manifest(paths.data_dir, paths.data_manifest)
    get_logger(__name__).info("Wrote %s with %d files", paths.data_manifest, len(manifest["files"]))
