"""Logging setup and helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit


class UTCFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z"


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(
        UTCFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(component)


def redact_url(url: str) -> str:
    """Remove query string and fragment from URLs (signed params)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def job_log_extra(backend_job_id: str | None) -> str:
    if backend_job_id:
        return f" job={backend_job_id}"
    return ""
