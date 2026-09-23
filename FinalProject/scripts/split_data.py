"""
Script: split_data.py
Splits the 30,000-row Credit Default dataset into 4 realistic partitions:
1. train_baseline.csv (15,000 samples): Baseline customers (older demographic, standard limit)
2. stream_normal.csv (5,000 samples): Normal incoming production traffic (PSI < 0.10)
3. stream_drifted.csv (5,000 samples): Drifted traffic (Gen-Z / younger demographic: AGE <= 29, PSI >= 0.25)
4. ground_truth_feedback.csv (5,000 samples): Ground truth delayed feedback for retraining
"""

import os
import shutil
import pandas as pd
import numpy as np


def split_credit_data():
    raw_source = os.path.join(
        os.path.dirname(__file__), "..", "..", "Lab2", "data", "credit_default.csv"
    )
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    raw_dest_dir = os.path.join(data_dir, "raw")
    os.makedirs(raw_dest_dir, exist_ok=True)

    # 1. Copy raw file
    raw_dest = os.path.join(raw_dest_dir, "credit_default.csv")
    if not os.path.exists(raw_dest):
        shutil.copyfile(raw_source, raw_dest)
        print(f"Copied raw data to {raw_dest}")

    # 2. Load dataset
    df = pd.read_csv(raw_source)
    print(f"Original dataset shape: {df.shape}")

    # Set random seed for reproducibility
    np.random.seed(42)

    # Separate older demographic (AGE >= 30) and younger demographic (AGE < 30)
    df_older = (
        df[df["AGE"] >= 30].sample(frac=1.0, random_state=42).reset_index(drop=True)
    )
    df_younger = (
        df[df["AGE"] < 30].sample(frac=1.0, random_state=42).reset_index(drop=True)
    )

    print(
        f"Older cohort (AGE >= 30): {len(df_older)} records (Mean age: {df_older['AGE'].mean():.1f})"
    )
    print(
        f"Younger cohort (AGE < 30): {len(df_younger)} records (Mean age: {df_younger['AGE'].mean():.1f})"
    )

    # Partition 1: Baseline training (15,000 records from older cohort)
    baseline_df = df_older.iloc[:15000].copy()
    baseline_path = os.path.join(data_dir, "train_baseline.csv")
    baseline_df.to_csv(baseline_path, index=False)
    print(
        f"Saved {len(baseline_df)} records to {baseline_path} (Mean age: {baseline_df['AGE'].mean():.1f})"
    )

    # Partition 2: Normal Stream (5,000 records from remaining older cohort)
    normal_stream_df = df_older.iloc[15000:20000].copy()
    normal_path = os.path.join(data_dir, "stream_normal.csv")
    normal_stream_df.to_csv(normal_path, index=False)
    print(
        f"Saved {len(normal_stream_df)} records to {normal_path} (Mean age: {normal_stream_df['AGE'].mean():.1f})"
    )

    # Partition 3: Drifted Stream (5,000 records from younger cohort - Marketing campaign)
    drifted_df = df_younger.iloc[:5000].copy()

    # Assign unique request_id to simulate inference logs
    request_ids = [f"req_{idx:06d}" for idx in range(1, len(drifted_df) + 1)]
    drifted_df.insert(0, "request_id", request_ids)

    # Separate features and target
    drifted_features = drifted_df.drop(columns=["default_payment_next_month"])
    drifted_path = os.path.join(data_dir, "stream_drifted.csv")
    drifted_features.to_csv(drifted_path, index=False)
    print(
        f"Saved {len(drifted_features)} records to {drifted_path} (Mean age: {drifted_features['AGE'].mean():.1f})"
    )

    # Partition 4: Ground Truth Feedback (5,000 records with request_id and target)
    ground_truth_df = drifted_df[["request_id", "default_payment_next_month"]].copy()
    gt_path = os.path.join(data_dir, "ground_truth_feedback.csv")
    ground_truth_df.to_csv(gt_path, index=False)
    print(f"Saved {len(ground_truth_df)} records to {gt_path}")

    print("\nData splitting completed successfully!")


if __name__ == "__main__":
    split_credit_data()
