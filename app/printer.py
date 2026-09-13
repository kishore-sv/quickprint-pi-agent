"""Printer abstraction and factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings
    from app.models import PrintSettings


class PrinterJobState(str, Enum):
    PENDING = "pending"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


@dataclass
class PrinterJobStatus:
    printer_job_id: str
    state: PrinterJobState
    message: str | None = None


@dataclass
class SubmitResult:
    printer_job_id: str


class ExistingJobLookupStatus(str, Enum):
    NOT_FOUND = "not_found"
    FOUND = "found"
    AMBIGUOUS = "ambiguous"
    LOOKUP_FAILED = "lookup_failed"


@dataclass
class ExistingJobLookup:
    status: ExistingJobLookupStatus
    printer_job_id: str | None = None
    message: str | None = None


class PrinterError(Exception):
    """Printer operation failed."""


class PrinterUnavailableError(PrinterError):
    """Printer or CUPS scheduler unavailable."""


class PrinterSubmissionError(PrinterError):
    """Job submission or cancel failed."""


class PrinterSubmissionUncertainError(PrinterError):
    """Submission outcome unknown; do not retry or resubmit."""


class Printer(ABC):
    @abstractmethod
    async def submit(
        self,
        file_path: Path,
        backend_job_id: str,
        settings: PrintSettings,
    ) -> SubmitResult:
        ...

    @abstractmethod
    async def get_status(self, printer_job_id: str) -> PrinterJobStatus:
        ...

    @abstractmethod
    async def cancel(self, printer_job_id: str) -> None:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    async def is_available(self) -> bool:
        return await self.health_check()

    async def get_printer_info(self) -> dict[str, str | bool]:
        return {"available": await self.is_available()}

    async def find_existing_job(self, backend_job_id: str) -> ExistingJobLookup:
        """Search for an already-submitted printer job for this backend job id."""
        return ExistingJobLookup(status=ExistingJobLookupStatus.NOT_FOUND)


def create_printer(settings: Settings) -> Printer:
    if settings.printer_mode == "mock":
        from app.mock_printer import MockPrinter

        return MockPrinter(
            delay_seconds=settings.mock_print_delay_seconds,
            simulate_failure=settings.mock_print_failure,
        )
    if settings.printer_mode == "cups":
        from app.cups import CupsPrinter

        return CupsPrinter(
            printer_name=settings.cups_printer_name,
            command_timeout_seconds=settings.cups_command_timeout_seconds,
        )
    raise ValueError(f"Unknown printer mode: {settings.printer_mode}")
