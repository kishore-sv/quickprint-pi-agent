"""Logging setup and helpers."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_FILE = PROJECT_ROOT / "logs" / "agent.log"

_SECRET_PATTERNS = (
    re.compile(r"(AGENT_SECRET|AGENT_TOKEN)\s*[=:]\s*\S+", re.I),
    re.compile(r"Authorization:\s*Bearer\s+\S+", re.I),
    re.compile(r"Bearer\s+[^\s]+", re.I),
)


class UTCFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z"


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for pattern in _SECRET_PATTERNS:
                if "Authorization" in pattern.pattern or "Bearer" in pattern.pattern:
                    msg = pattern.sub("Authorization: Bearer ***", msg)
                else:
                    msg = pattern.sub(
                        lambda m: m.group(0).split("=")[0] + "=***", msg
                    )
            record.msg = redact_url_in_text(msg)
        if record.args:
            record.args = tuple(
                redact_url_in_text(str(a)) if isinstance(a, str) else a
                for a in record.args
            )
        return True


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    formatter = UTCFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    redaction = SecretRedactionFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(redaction)
    root.addHandler(stream_handler)

    path = log_file or DEFAULT_LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redaction)
    root.addHandler(file_handler)


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(component)


def redact_url(url: str) -> str:
    """Remove query string and fragment from URLs (signed params)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def redact_url_in_text(text: str) -> str:
    """Redact query strings on http(s) URLs embedded in log text."""
    return re.sub(
        r"(https?://[^\s?]+)\?[^\s]*",
        r"\1",
        text,
    )


def job_context(
    job_id: str | None = None,
    cups_job_id: str | None = None,
    event: str | None = None,
    status: str | None = None,
) -> str:
    parts: list[str] = []
    if job_id:
        parts.append(f"job_id={job_id}")
    if cups_job_id:
        parts.append(f"cups_job_id={cups_job_id}")
    if event:
        parts.append(f"event={event}")
    if status:
        parts.append(f"status={status}")
    return " ".join(parts)


def format_job_summary(
    job_id: str,
    filename: str | None,
    copies: int,
    paper: str,
    color: str,
    duplex: bool,
) -> str:
    name = filename or "job.pdf"
    duplex_str = "true" if duplex else "false"
    return (
        f"------------------------------------------------\n"
        f"PRINT JOB\n"
        f"job_id: {job_id}\n"
        f"file: {name}\n"
        f"copies: {copies}\n"
        f"paper: {paper}\n"
        f"color: {color}\n"
        f"duplex: {duplex_str}\n"
        f"------------------------------------------------"
    )
