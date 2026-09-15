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
from app.cups_discovery import parse_lpstat_printer_status
from app.cups_job_identity import cups_job_title, lpstat_text_contains_exact_title
from app.cups_options import build_lp_argv
from app.logger import get_logger, job_context
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

log = get_logger("cups")

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


def _job_line_from_lpstat_listing(stdout: str, job_id: str) -> str | None:
    """Return the lpstat listing line for a CUPS job id, if present."""
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == job_id or stripped.startswith(f"{job_id} "):
            return stripped
    return None


def _lpstat_queue_list_args(printer_name: str, *, which: str = "not-completed") -> list[str]:
    """Build lpstat argv to list jobs on a printer queue (never a job id)."""
    if which == "completed":
        return ["lpstat", "-W", "completed", "-o", printer_name]
    if which == "all":
        return ["lpstat", "-W", "all", "-o", printer_name]
    return ["lpstat", "-o", printer_name]


def _build_runner_env(cups_server: str | None) -> AsyncSubprocessCupsRunner:
    extra: dict[str, str] = {}
    if cups_server:
        extra["CUPS_SERVER"] = cups_server
    return AsyncSubprocessCupsRunner(extra_env=extra or None)


class CupsPrinter(Printer):
    def __init__(
        self,
        printer_name: str,
        runner: CupsCommandRunner | None = None,
        command_timeout_seconds: float = 30.0,
        cups_server: str | None = None,
    ) -> None:
        self._printer_name = printer_name
        self._cups_server = cups_server or None
        self._runner = runner or _build_runner_env(self._cups_server)
        self._timeout = command_timeout_seconds

    async def _run(self, *args: str) -> CommandResult:
        return await self._runner.run(list(args), self._timeout)

    async def is_available(self) -> bool:
        info = await self.get_printer_info()
        return bool(
            info.get("available")
            and info.get("enabled", True)
            and info.get("accepting_jobs", True)
        )

    async def get_printer_info(self) -> dict[str, str | bool]:
        info: dict[str, str | bool] = {
            "name": self._printer_name,
            "available": False,
            "enabled": False,
            "accepting_jobs": False,
            "cups_server": self._cups_server or "local",
        }
        result = await self._run("lpstat", "-p", self._printer_name)
        parsed = parse_lpstat_printer_status(
            result.stdout if result.returncode == 0 else result.stderr
        )
        info["available"] = result.returncode == 0 and bool(parsed.get("exists"))
        info["enabled"] = bool(parsed.get("enabled"))
        info["accepting_jobs"] = bool(parsed.get("accepting_jobs"))
        if parsed.get("status_line"):
            info["status_line"] = str(parsed["status_line"])
        if result.stderr.strip():
            info["stderr"] = result.stderr.strip()[:200]
        sched = await self._run("lpstat", "-r")
        if sched.returncode == 0 and sched.stdout.strip():
            info["scheduler"] = sched.stdout.strip().splitlines()[0]
            info["cups_scheduler_running"] = (
                "scheduler is running" in sched.stdout.lower()
            )
        else:
            info["cups_scheduler_running"] = False
        return info

    async def find_existing_job(self, backend_job_id: str) -> ExistingJobLookup:
        try:
            marker = cups_job_title(backend_job_id)
        except ValueError as e:
            return ExistingJobLookup(
                status=ExistingJobLookupStatus.LOOKUP_FAILED,
                message=str(e),
            )

        log.info(
            "CUPS job lookup %s",
            job_context(job_id=backend_job_id, event="cups_lookup"),
        )
        matches: set[str] = set()
        listings_failed = 0

        for list_args in (
            _lpstat_queue_list_args(self._printer_name),
            _lpstat_queue_list_args(self._printer_name, which="completed"),
        ):
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
        found_id = next(iter(matches))
        log.info(
            "CUPS job adopted %s",
            job_context(job_id=backend_job_id, cups_job_id=found_id, event="cups_adopted"),
        )
        return ExistingJobLookup(
            status=ExistingJobLookupStatus.FOUND,
            printer_job_id=found_id,
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
                f"Printer '{self._printer_name}' is not available or not accepting jobs"
            )

        title = cups_job_title(backend_job_id)
        cmd = build_lp_argv(self._printer_name, str(file_path), settings)
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

        log.info(
            "Submitting to CUPS %s printer=%s",
            job_context(job_id=backend_job_id, event="cups_submit"),
            self._printer_name,
        )
        log.debug("CUPS lp command argv0=%s argc=%d", titled_cmd[0], len(titled_cmd))

        try:
            result = await self._runner.run(titled_cmd, self._timeout)
        except CupsCommandTimeoutError:
            log.warning(
                "CUPS lp timeout %s",
                job_context(job_id=backend_job_id, event="cups_submit_timeout"),
            )
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
            log.error(
                "CUPS submission failed %s reason=%s",
                job_context(job_id=backend_job_id, event="cups_submit_failed"),
                msg[:200],
            )
            raise PrinterSubmissionError(f"lp failed ({result.returncode}): {msg}")

        match = _REQUEST_ID_RE.search(result.stdout)
        if not match:
            raise PrinterSubmissionError(
                f"Could not parse CUPS job id from: {result.stdout.strip()}"
            )
        cups_job_id = match.group(1)
        log.info(
            "CUPS job created %s",
            job_context(
                job_id=backend_job_id,
                cups_job_id=cups_job_id,
                event="cups_job_created",
            ),
        )
        return SubmitResult(printer_job_id=cups_job_id)

    async def get_status(self, printer_job_id: str) -> PrinterJobStatus:
        last_err = ""
        listings = (
            _lpstat_queue_list_args(self._printer_name),
            _lpstat_queue_list_args(self._printer_name, which="completed"),
        )

        for list_args in listings:
            try:
                result = await self._run(*list_args)
            except CupsCommandTimeoutError as e:
                return PrinterJobStatus(
                    printer_job_id=printer_job_id,
                    state=PrinterJobState.UNKNOWN,
                    message=str(e),
                )

            if result.returncode != 0:
                last_err = result.stderr.strip() or result.stdout.strip()
                continue

            line = _job_line_from_lpstat_listing(result.stdout, printer_job_id)
            if not line:
                continue

            state = _parse_job_state(line, result.stderr)
            log.debug(
                "CUPS status %s",
                job_context(cups_job_id=printer_job_id, status=state.value),
            )
            return PrinterJobStatus(printer_job_id=printer_job_id, state=state)

        return PrinterJobStatus(
            printer_job_id=printer_job_id,
            state=PrinterJobState.UNKNOWN,
            message=(
                last_err
                or f"CUPS job {printer_job_id!r} not found on queue {self._printer_name!r}"
            ),
        )

    async def cancel(self, printer_job_id: str) -> None:
        log.info(
            "Cancelling CUPS job %s",
            job_context(cups_job_id=printer_job_id, event="cups_cancel"),
        )
        try:
            result = await self._run("cancel", printer_job_id)
        except CupsCommandTimeoutError as e:
            raise PrinterSubmissionError(str(e)) from e
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise PrinterSubmissionError(f"cancel failed: {msg}")

    async def health_check(self) -> bool:
        try:
            info = await self.get_printer_info()
        except Exception:
            return False
        return bool(info.get("available")) and bool(info.get("cups_scheduler_running"))
