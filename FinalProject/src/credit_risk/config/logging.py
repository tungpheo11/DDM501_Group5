"""Logging bootstrap driven by ``configs/logging.yaml``.

``LOG_FORMAT`` selects the console formatter: ``json`` (default, one JSON object
per line for log shippers) or ``text`` (human-readable, for local debugging).
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
from datetime import UTC, datetime
from typing import Any

import yaml

from credit_risk.config.settings import Settings, get_settings
from credit_risk.utils.request_context import get_request_id

_configured = False

# Applicant attributes of the UCI dataset. They must never reach the logs raw.
PII_FIELDS = frozenset(
    {
        "LIMIT_BAL",
        "SEX",
        "EDUCATION",
        "MARRIAGE",
        "AGE",
        *(f"PAY_{i}" for i in (0, 2, 3, 4, 5, 6)),
        *(f"BILL_AMT{i}" for i in range(1, 7)),
        *(f"PAY_AMT{i}" for i in range(1, 7)),
        "features",
        "payload",
        "applicant",
        "applicants",
    }
)
REDACTED = "[REDACTED]"

_RESERVED_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",  # uvicorn's ANSI-colored duplicate of ``message``
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: REDACTED if key in PII_FIELDS else _redact(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Render records as single-line JSON with request id and redacted ``extra`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize one record."""
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            entry["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key == "request_id" or key.startswith("_"):
                continue
            entry[key] = REDACTED if key in PII_FIELDS else _redact(value)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def setup_logging(settings: Settings | None = None, *, force: bool = False) -> None:
    """Configure logging once per process from the YAML dictConfig.

    Falls back to ``logging.basicConfig`` when the YAML file is missing so that
    entrypoints never crash because of logging setup.
    """
    global _configured
    if _configured and not force:
        return

    cfg = settings or get_settings()
    config_path = cfg.logging_config
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            config: dict[str, Any] = yaml.safe_load(handle) or {}
        log_format = os.getenv("LOG_FORMAT", "").strip().lower()
        console = (config.get("handlers") or {}).get("console")
        if log_format and console is not None and log_format in (config.get("formatters") or {}):
            console["formatter"] = log_format
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    logging.getLogger().setLevel(cfg.log_level)
    logging.getLogger("credit_risk").setLevel(cfg.log_level)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger; call :func:`setup_logging` from entrypoints."""
    return logging.getLogger(name)
