"""CUPS printer integration via CLI (for Raspberry Pi production)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.models import PrintSettings
from app.printer import (
    Printer,
    PrinterError,
    PrinterJobState,
    PrinterJobStatus,
    SubmitResult,
)

_REQUEST_ID_RE = re.compile(r"request id is ([^\s]+)", re.IGNORECASE)


class CupsPrinter(Printer):
    def __init__(self, printer_name: str) -> None:
        self._printer_name = printer_name

    async def _run(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )

    async def submit(
        self,
        file_path: Path,
        backend_job_id: str,
        settings: PrintSettings,
    ) -> SubmitResult:
        if not file_path.is_file():
            raise PrinterError(f"File not found: {file_path}")

        cmd = ["lp", "-d", self._printer_name, str(file_path)]
        if settings.copies > 1:
            cmd.extend(["-n", str(settings.copies)])

        code, stdout, stderr = await self._run(*cmd)
        if code != 0:
            raise PrinterError(f"lp failed ({code}): {stderr.strip() or stdout.strip()}")

        match = _REQUEST_ID_RE.search(stdout)
        if not match:
            raise PrinterError(f"Could not parse CUPS job id from: {stdout.strip()}")
        return SubmitResult(printer_job_id=match.group(1))

    async def get_status(self, printer_job_id: str) -> PrinterJobStatus:
        code, stdout, stderr = await self._run("lpstat", "-o", printer_job_id)
        if code != 0:
            # Job may have completed and left the queue
            code2, stdout2, _ = await self._run("lpstat", "-W", "completed", "-o", printer_job_id)
            if code2 == 0 and printer_job_id in stdout2:
                return PrinterJobStatus(
                    printer_job_id=printer_job_id,
                    state=PrinterJobState.COMPLETED,
                )
            if "Unable to locate" in stderr or "No such file" in stderr:
                return PrinterJobStatus(
                    printer_job_id=printer_job_id,
                    state=PrinterJobState.UNKNOWN,
                    message=stderr.strip(),
                )
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.UNKNOWN,
                message=stderr.strip() or stdout.strip(),
            )

        text = stdout.lower()
        if "processing" in text or "printing" in text:
            state = PrinterJobState.PRINTING
        elif "pending" in text or "held" in text:
            state = PrinterJobState.PENDING
        else:
            state = PrinterJobState.PRINTING
        return PrinterJobStatus(printer_job_id=printer_job_id, state=state)

    async def cancel(self, printer_job_id: str) -> None:
        code, stdout, stderr = await self._run("cancel", printer_job_id)
        if code != 0:
            raise PrinterError(f"cancel failed: {stderr.strip() or stdout.strip()}")

    async def health_check(self) -> bool:
        code, _, _ = await self._run("lpstat", "-p", self._printer_name)
        return code == 0
