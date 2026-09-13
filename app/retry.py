"""Bounded retry policy for recoverable failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.downloader import DownloadError, PermanentDownloadError, RetryableDownloadError
from app.printer import (
    PrinterError,
    PrinterSubmissionError,
    PrinterSubmissionUncertainError,
    PrinterUnavailableError,
)


class FailureKind(str, Enum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float

    def delay_for_attempt(self, attempt_count: int) -> float:
        if attempt_count <= 0:
            return self.base_delay_seconds
        delay = self.base_delay_seconds * (2 ** (attempt_count - 1))
        return min(delay, self.max_delay_seconds)

    def should_retry(self, attempt_count: int) -> bool:
        return attempt_count < self.max_attempts


def classify_download_error(exc: DownloadError) -> FailureKind:
    if isinstance(exc, RetryableDownloadError):
        return FailureKind.RETRYABLE
    if isinstance(exc, PermanentDownloadError):
        return FailureKind.PERMANENT
    return FailureKind.RETRYABLE


def classify_printer_error(exc: PrinterError) -> FailureKind:
    if isinstance(exc, (PrinterUnavailableError,)):
        return FailureKind.RETRYABLE
    if isinstance(exc, (PrinterSubmissionError, PrinterSubmissionUncertainError)):
        return FailureKind.PERMANENT
    if isinstance(exc, ValueError):
        return FailureKind.PERMANENT
    return FailureKind.PERMANENT
