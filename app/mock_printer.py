"""Mock printer for development and tests."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from app.models import PrintSettings
from app.printer import (
    Printer,
    PrinterError,
    PrinterJobState,
    PrinterJobStatus,
    SubmitResult,
)


@dataclass
class _MockJob:
    backend_job_id: str
    file_path: Path
    submitted_at: float
    delay_seconds: float
    simulate_failure: bool
    cancelled: bool = False


class MockPrinter(Printer):
    def __init__(
        self,
        delay_seconds: float = 0.1,
        simulate_failure: bool = False,
    ) -> None:
        self._delay_seconds = delay_seconds
        self._simulate_failure = simulate_failure
        self._jobs: dict[str, _MockJob] = {}
        self.submit_count = 0

    async def submit(
        self,
        file_path: Path,
        backend_job_id: str,
        settings: PrintSettings,
    ) -> SubmitResult:
        if not file_path.is_file():
            raise PrinterError(f"File not found: {file_path}")
        self.submit_count += 1
        job_id = f"mock-{secrets.token_hex(8)}"
        self._jobs[job_id] = _MockJob(
            backend_job_id=backend_job_id,
            file_path=file_path,
            submitted_at=time.monotonic(),
            delay_seconds=self._delay_seconds,
            simulate_failure=self._simulate_failure,
        )
        return SubmitResult(printer_job_id=job_id)

    async def get_status(self, printer_job_id: str) -> PrinterJobStatus:
        job = self._jobs.get(printer_job_id)
        if job is None:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.UNKNOWN,
                message="Mock job not found",
            )
        if job.cancelled:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.CANCELLED,
            )
        elapsed = time.monotonic() - job.submitted_at
        if job.simulate_failure and elapsed >= job.delay_seconds * 0.5:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.FAILED,
                message="Simulated printer failure",
            )
        if elapsed < job.delay_seconds * 0.3:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.PENDING,
            )
        if elapsed < job.delay_seconds:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.PRINTING,
            )
        return PrinterJobStatus(
            printer_job_id=printer_job_id,
            state=PrinterJobState.COMPLETED,
        )

    async def cancel(self, printer_job_id: str) -> None:
        job = self._jobs.get(printer_job_id)
        if job:
            job.cancelled = True

    async def health_check(self) -> bool:
        return True
