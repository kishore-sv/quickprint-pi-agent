"""CUPS printer integration via CLI (for Raspberry Pi production)."""

from __future__ import annotations

import re
from pathlib import Path

from app.cups_command import (
    AsyncSubprocessCupsRunner,
    CommandResult,
    CupsCommandRunner,
    CupsCommandTimeoutError,
)
from app.cups_job_identity import cups_job_title, lpstat_text_contains_exact_title
from app.cups_options import build_lp_argv
from app.models import PrintSettings
from app.printer import (
    ExistingJobLookup,
    ExistingJobLookupStatus,
    Printer,
    PrinterJobState,
    PrinterJobStatus,
    PrinterSubmissionError,
    PrinterSubmissionUncertainError,
    PrinterUnavailableError,
    SubmitResult,
)

_REQUEST_ID_RE = re.compile(r"request id is ([^\s]+)", re.IGNORECASE)
_LPSTAT_JOB_ID_RE = re.compile(r"^(\S+?-\d+)\s+")


def _parse_job_state(stdout: str, stderr: str) -> PrinterJobState:
    text = (stdout + stderr).lower()
    if "completed" in text:
        return PrinterJobState.COMPLETED
    if "canceled" in text or "cancelled" in text:
        return PrinterJobState.CANCELLED
    if "aborted" in text:
        return PrinterJobState.FAILED
    if "processing" in text or "printing" in text:
        return PrinterJobState.PRINTING
    if "pending" in text or "held" in text or "queued" in text:
        return PrinterJobState.PENDING
    return PrinterJobState.UNKNOWN


def _job_ids_from_lpstat_listing(stdout: str) -> list[str]:
    ids: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _LPSTAT_JOB_ID_RE.match(line)
        if match:
            ids.append(match.group(1))
    return ids


class CupsPrinter(Printer):
    def __init__(
        self,
        printer_name: str,
        runner: CupsCommandRunner | None = None,
        command_timeout_seconds: float = 30.0,
    ) -> None:
        self._printer_name = printer_name
        self._runner = runner or AsyncSubprocessCupsRunner()
        self._timeout = command_timeout_seconds

    async def _run(self, *args: str) -> CommandResult:
        return await self._runner.run(list(args), self._timeout)

    async def is_available(self) -> bool:
        return await self.health_check()

    async def get_printer_info(self) -> dict[str, str | bool]:
        info: dict[str, str | bool] = {
            "name": self._printer_name,
            "available": False,
        }
        code, stdout, stderr = await self._run("lpstat", "-p", self._printer_name)
        info["available"] = code == 0
        if stdout.strip():
            info["status_line"] = stdout.strip().splitlines()[0]
        if stderr.strip():
            info["stderr"] = stderr.strip()[:200]
        code_r, stdout_r, _ = await self._run("lpstat", "-r")
        if code_r == 0 and stdout_r.strip():
            info["scheduler"] = stdout_r.strip().splitlines()[0]
            info["cups_scheduler_running"] = "scheduler is running" in stdout_r.lower()
        return info

    async def find_existing_job(self, backend_job_id: str) -> ExistingJobLookup:
        try:
            marker = cups_job_title(backend_job_id)
        except ValueError as e:
            return ExistingJobLookup(
                status=ExistingJobLookupStatus.LOOKUP_FAILED,
                message=str(e),
            )

        matches: set[str] = set()
        listings_failed = 0

        for list_args in (["lpstat", "-o"], ["lpstat", "-W", "completed", "-o"]):
            try:
                result = await self._run(*list_args)
            except CupsCommandTimeoutError as e:
                return ExistingJobLookup(
                    status=ExistingJobLookupStatus.LOOKUP_FAILED,
                    message=str(e),
                )
            if result.returncode != 0:
                listings_failed += 1
                continue

            for job_id in _job_ids_from_lpstat_listing(result.stdout):
                detail = await self._run("lpstat", "-l", "-o", job_id)
                if detail.returncode == 0 and lpstat_text_contains_exact_title(
                    detail.stdout, marker
                ):
                    matches.add(job_id)

        if listings_failed == 2:
            return ExistingJobLookup(
                status=ExistingJobLookupStatus.LOOKUP_FAILED,
                message="Could not list CUPS jobs for recovery lookup",
            )
        if not matches:
            return ExistingJobLookup(status=ExistingJobLookupStatus.NOT_FOUND)
        if len(matches) > 1:
            return ExistingJobLookup(
                status=ExistingJobLookupStatus.AMBIGUOUS,
                message=f"Multiple CUPS jobs match {marker}: {sorted(matches)}",
            )
        return ExistingJobLookup(
            status=ExistingJobLookupStatus.FOUND,
            printer_job_id=next(iter(matches)),
        )

    async def submit(
        self,
        file_path: Path,
        backend_job_id: str,
        settings: PrintSettings,
    ) -> SubmitResult:
        if not file_path.exists():
            raise PrinterSubmissionError(f"File not found: {file_path}")
        if not file_path.is_file():
            raise PrinterSubmissionError(f"Not a regular file: {file_path}")

        if not await self.is_available():
            raise PrinterUnavailableError(
                f"Printer '{self._printer_name}' is not available"
            )

        title = cups_job_title(backend_job_id)
        cmd = build_lp_argv(self._printer_name, str(file_path), settings)
        # Insert -t <title> after printer destination
        titled_cmd: list[str] = []
        i = 0
        while i < len(cmd):
            titled_cmd.append(cmd[i])
            if cmd[i] == "-d" and i + 1 < len(cmd):
                titled_cmd.append(cmd[i + 1])
                titled_cmd.extend(["-t", title])
                i += 2
                continue
            i += 1
        if "-t" not in titled_cmd:
            titled_cmd = [cmd[0], "-t", title] + cmd[1:]

        try:
            result = await self._runner.run(titled_cmd, self._timeout)
        except CupsCommandTimeoutError:
            lookup = await self.find_existing_job(backend_job_id)
            if (
                lookup.status == ExistingJobLookupStatus.FOUND
                and lookup.printer_job_id
            ):
                return SubmitResult(printer_job_id=lookup.printer_job_id)
            if lookup.status == ExistingJobLookupStatus.NOT_FOUND:
                raise PrinterSubmissionUncertainError(
                    "lp timed out; no matching CUPS job found; reconciliation required"
                )
            raise PrinterSubmissionUncertainError(
                lookup.message
                or "lp timed out; could not determine CUPS job state; reconciliation required"
            )

        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise PrinterSubmissionError(f"lp failed ({result.returncode}): {msg}")

        match = _REQUEST_ID_RE.search(result.stdout)
        if not match:
            raise PrinterSubmissionError(
                f"Could not parse CUPS job id from: {result.stdout.strip()}"
            )
        return SubmitResult(printer_job_id=match.group(1))

    async def get_status(self, printer_job_id: str) -> PrinterJobStatus:
        try:
            result = await self._run("lpstat", "-o", printer_job_id)
        except CupsCommandTimeoutError as e:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.UNKNOWN,
                message=str(e),
            )

        if result.returncode == 0:
            state = _parse_job_state(result.stdout, result.stderr)
            return PrinterJobStatus(printer_job_id=printer_job_id, state=state)

        completed = await self._run(
            "lpstat", "-W", "completed", "-o", printer_job_id
        )
        if completed.returncode == 0 and printer_job_id in completed.stdout:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.COMPLETED,
            )

        err = result.stderr.strip() or result.stdout.strip()
        if "Unable to locate" in err or "No such file" in err:
            return PrinterJobStatus(
                printer_job_id=printer_job_id,
                state=PrinterJobState.UNKNOWN,
                message=err,
            )
        return PrinterJobStatus(
            printer_job_id=printer_job_id,
            state=PrinterJobState.UNKNOWN,
            message=err or "Could not determine CUPS job state",
        )

    async def cancel(self, printer_job_id: str) -> None:
        try:
            result = await self._run("cancel", printer_job_id)
        except CupsCommandTimeoutError as e:
            raise PrinterSubmissionError(str(e)) from e
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise PrinterSubmissionError(f"cancel failed: {msg}")

    async def health_check(self) -> bool:
        try:
            result = await self._run("lpstat", "-p", self._printer_name)
        except CupsCommandTimeoutError:
            return False
        return result.returncode == 0
