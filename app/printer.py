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


class PrinterError(Exception):
    """Printer operation failed."""


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


def create_printer(settings: Settings) -> Printer:
    if settings.printer_mode == "mock":
        from app.mock_printer import MockPrinter

        return MockPrinter(
            delay_seconds=settings.mock_print_delay_seconds,
            simulate_failure=settings.mock_print_failure,
        )
    if settings.printer_mode == "cups":
        from app.cups import CupsPrinter

        return CupsPrinter(printer_name=settings.cups_printer_name)
    raise ValueError(f"Unknown printer mode: {settings.printer_mode}")
