"""Partition the 30k raw dataset into baseline, production streams and delayed labels.

Partitions (deterministic, ``random_state=42``):

1. ``reference/train_baseline.csv`` (15,000): older cohort (AGE >= 30), baseline training data.
2. ``processed/stream_normal.csv`` (5,000): older cohort, production traffic without drift.
3. ``processed/stream_drifted.csv`` (5,000): younger cohort (AGE < 30), unlabeled drifted traffic.
4. ``processed/ground_truth_feedback.csv`` (5,000): delayed labels for the drifted stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from credit_risk.config import get_logger, get_settings
from credit_risk.data.schema import REQUEST_ID_COLUMN, TARGET_COLUMN

logger = get_logger(__name__)

AGE_COHORT_BOUNDARY = 30
BASELINE_SIZE = 15_000
STREAM_SIZE = 5_000
RANDOM_STATE = 42


@dataclass(frozen=True)
class SplitOutputs:
    """Paths written by :func:`split_credit_data`."""

    baseline: Path
    normal_stream: Path
    drifted_stream: Path
    ground_truth: Path


def split_credit_data(
    raw_path: Path | None = None,
    reference_dir: Path | None = None,
    processed_dir: Path | None = None,
) -> SplitOutputs:
    """Split the raw dataset into the four partitions described in the module docstring."""
    paths = get_settings().paths
    raw_file = raw_path or paths.raw_data
    ref_dir = reference_dir or paths.reference_dir
    proc_dir = processed_dir or paths.processed_dir
    ref_dir.mkdir(parents=True, exist_ok=True)
    proc_dir.mkdir(parents=True, exist_ok=True)

    if not raw_file.exists():
        raise FileNotFoundError(f"Raw dataset not found at {raw_file}")

    df = pd.read_csv(raw_file)
    logger.info("Original dataset shape: %s", df.shape)

    df_older = df[df["AGE"] >= AGE_COHORT_BOUNDARY].sample(frac=1.0, random_state=RANDOM_STATE).reset_index(drop=True)
    df_younger = df[df["AGE"] < AGE_COHORT_BOUNDARY].sample(frac=1.0, random_state=RANDOM_STATE).reset_index(drop=True)
    logger.info("Older cohort (AGE >= 30): %d records (mean age %.1f)", len(df_older), df_older["AGE"].mean())
    logger.info("Younger cohort (AGE < 30): %d records (mean age %.1f)", len(df_younger), df_younger["AGE"].mean())

    outputs = SplitOutputs(
        baseline=ref_dir / "train_baseline.csv",
        normal_stream=proc_dir / "stream_normal.csv",
        drifted_stream=proc_dir / "stream_drifted.csv",
        ground_truth=proc_dir / "ground_truth_feedback.csv",
    )

    baseline_df = df_older.iloc[:BASELINE_SIZE].copy()
    baseline_df.to_csv(outputs.baseline, index=False)
    logger.info("Saved %d records to %s", len(baseline_df), outputs.baseline)

    normal_df = df_older.iloc[BASELINE_SIZE : BASELINE_SIZE + STREAM_SIZE].copy()
    normal_df.to_csv(outputs.normal_stream, index=False)
    logger.info("Saved %d records to %s", len(normal_df), outputs.normal_stream)

    drifted_df = df_younger.iloc[:STREAM_SIZE].copy()
    drifted_df.insert(0, REQUEST_ID_COLUMN, [f"req_{idx:06d}" for idx in range(1, len(drifted_df) + 1)])
    drifted_df.drop(columns=[TARGET_COLUMN]).to_csv(outputs.drifted_stream, index=False)
    logger.info("Saved %d records to %s", len(drifted_df), outputs.drifted_stream)

    drifted_df[[REQUEST_ID_COLUMN, TARGET_COLUMN]].to_csv(outputs.ground_truth, index=False)
    logger.info("Saved %d records to %s", len(drifted_df), outputs.ground_truth)

    return outputs
