"""Entrypoint: split data/raw/credit_default.csv into reference/processed partitions."""

from credit_risk.config import setup_logging
from credit_risk.data.splitting import split_credit_data

if __name__ == "__main__":
    setup_logging()
    split_credit_data()
