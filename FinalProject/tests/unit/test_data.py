import pandas as pd
import pytest

from credit_risk.data.loader import get_train_val_split, load_data
from credit_risk.data.manifest import (
    build_manifest,
    find_entry,
    load_manifest,
    manifest_fingerprint,
    sha256_of,
    verify_file,
    write_manifest,
)
from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN
from credit_risk.data.splitting import split_credit_data
from credit_risk.features.preprocessing import create_preprocessor


def test_load_data_returns_features_and_target(settings):
    features, target = load_data(settings.paths.normal_stream)
    assert list(features.columns) == ALL_FEATURES
    assert target is not None and target.name == TARGET_COLUMN


def test_load_data_unlabeled_stream(settings):
    _, target = load_data(settings.paths.drifted_stream)
    assert target is None


def test_load_data_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"AGE": [30]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Missing required columns"):
        load_data(path)


def test_split_requires_target(settings):
    with pytest.raises(ValueError, match="target column missing"):
        get_train_val_split(settings.paths.drifted_stream)


def test_train_val_split_is_stratified(settings):
    x_train, x_val, y_train, y_val = get_train_val_split(settings.paths.baseline_data)
    assert len(x_val) == pytest.approx(0.2 * (len(x_train) + len(x_val)), abs=1)
    assert y_train.mean() == pytest.approx(y_val.mean(), abs=0.01)


def test_preprocessor_output_width(settings):
    features, _ = load_data(settings.paths.normal_stream)
    transformed = create_preprocessor(include_engineered=False).fit_transform(features.head(200))
    assert transformed.shape[0] == 200
    assert transformed.shape[1] > len(ALL_FEATURES) - 3


def test_split_credit_data_reproduces_committed_partitions(tmp_path, settings):
    outputs = split_credit_data(
        raw_path=settings.paths.raw_data, reference_dir=tmp_path / "reference", processed_dir=tmp_path / "processed"
    )
    assert sha256_of(outputs.baseline) == sha256_of(settings.paths.baseline_data)
    assert sha256_of(outputs.normal_stream) == sha256_of(settings.paths.normal_stream)
    assert sha256_of(outputs.drifted_stream) == sha256_of(settings.paths.drifted_stream)
    assert sha256_of(outputs.ground_truth) == sha256_of(settings.paths.ground_truth)


def test_split_credit_data_missing_raw(tmp_path):
    with pytest.raises(FileNotFoundError):
        split_credit_data(raw_path=tmp_path / "missing.csv", reference_dir=tmp_path, processed_dir=tmp_path)


def test_manifest_roundtrip(tmp_path):
    (tmp_path / "raw").mkdir()
    pd.DataFrame({"a": [1, 2]}).to_csv(tmp_path / "raw" / "x.csv", index=False)
    manifest = write_manifest(tmp_path, tmp_path / "manifest.json")
    assert manifest == load_manifest(tmp_path / "manifest.json")
    assert build_manifest(tmp_path)["files"][0] == {
        "path": "raw/x.csv",
        "sha256": sha256_of(tmp_path / "raw" / "x.csv"),
        "bytes": (tmp_path / "raw" / "x.csv").stat().st_size,
        "rows": 2,
        "columns": ["a"],
        "source": "unknown",
    }
    assert manifest["fingerprint"] == manifest_fingerprint(manifest["files"])
    assert manifest["dataset"]["url"].startswith("https://archive.ics.uci.edu/")


def test_manifest_fingerprint_is_order_independent_and_content_sensitive():
    files = [{"path": "b.csv", "sha256": "2"}, {"path": "a.csv", "sha256": "1"}]
    assert manifest_fingerprint(files) == manifest_fingerprint(list(reversed(files)))
    assert manifest_fingerprint(files) != manifest_fingerprint([{"path": "a.csv", "sha256": "x"}, files[0]])


def test_verify_file_against_committed_manifest(settings):
    manifest = load_manifest(settings.paths.data_manifest)
    assert find_entry(manifest, "raw/credit_default.csv")["source"].startswith("UCI")
    assert verify_file(manifest, settings.paths.data_dir, "reference/train_baseline.csv")
    assert not verify_file(manifest, settings.paths.data_dir, "raw/missing.csv")
