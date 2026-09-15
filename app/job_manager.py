"""Orchestrates print job lifecycle."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.cups_options import validate_print_settings
from app.database import Database
from app.downloader import Downloader, DownloadError
from app.logger import format_job_summary, get_logger, job_context
from app.models import (
    AssignedJob,
    JobRecord,
    JobStatus,
    TERMINAL_STATUSES,
    InvalidTransitionError,
    utc_now_iso,
)
from app.printer import (
    ExistingJobLookupStatus,
    Printer,
    PrinterError,
    PrinterJobState,
    PrinterJobStatus,
)
from app.retry import FailureKind, RetryPolicy, classify_download_error, classify_printer_error

log = get_logger("job_manager")

StateChangeCallback = Callable[
    [str, JobStatus, dict[str, Any]], Awaitable[None]
]


class JobManager:
    def __init__(
        self,
        db: Database,
        downloader: Downloader,
        printer: Printer,
        processing_dir: Path,
        completed_dir: Path,
        failed_dir: Path,
        incoming_dir: Path | None = None,
        on_state_change: StateChangeCallback | None = None,
        poll_interval_seconds: float = 1.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._db = db
        self._downloader = downloader
        self._printer = printer
        self._processing_dir = processing_dir
        self._completed_dir = completed_dir
        self._failed_dir = failed_dir
        self._incoming_dir = incoming_dir
        self._on_state_change = on_state_change
        self._poll_interval = poll_interval_seconds
        self._retry_policy = retry_policy or RetryPolicy(3, 1.0, 30.0)
        self._queue: asyncio.Queue[AssignedJob] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._shutdown = False

    def start(self) -> None:
        if self._incoming_dir:
            self._cleanup_stale_part_files(self._incoming_dir)
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        self._shutdown = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def enqueue_assigned(self, job: AssignedJob) -> None:
        await self._queue.put(job)

    async def handle_assigned(self, job: AssignedJob) -> None:
        existing = self._db.get_by_backend_id(job.backend_job_id)
        if existing is None:
            metadata = {
                "filename": job.filename,
                "file_url": job.file_url,
                "print_settings": job.print_settings.to_dict(),
            }
            record = self._db.create_job(job.backend_job_id, metadata)
            log.info(
                "Job received %s",
                job_context(job_id=job.backend_job_id, event="received"),
            )
            log.info(
                format_job_summary(
                    job.backend_job_id,
                    job.filename,
                    job.print_settings.copies,
                    job.print_settings.paper_size,
                    job.print_settings.color_mode,
                    job.print_settings.duplex,
                )
            )
            await self._emit(job.backend_job_id, JobStatus.RECEIVED)
            await self._process_new_job(job, record)
            return

        if existing.status in TERMINAL_STATUSES:
            log.info(
                "Ignoring duplicate assignment for terminal job job=%s status=%s",
                job.backend_job_id,
                existing.status.value,
            )
            await self._emit(existing.backend_job_id, existing.status)
            return

        await self._resume_job(job, existing)

    async def recover_unfinished_jobs(self) -> None:
        jobs = self._db.list_non_terminal_jobs()
        log.info("Recovering %d unfinished job(s)", len(jobs))
        for record in jobs:
            assigned = self._record_to_assigned(record)
            if assigned is None:
                continue
            await self._resume_job(assigned, record)

    async def reconcile_backend_status(self) -> None:
        """Re-report current status for in-flight and recently finished jobs after reconnect."""
        active = self._db.list_non_terminal_jobs()
        recent_terminal = self._db.list_recently_terminal_jobs(within_seconds=300)
        seen: set[str] = set()
        jobs = []
        for record in active + recent_terminal:
            if record.backend_job_id in seen:
                continue
            seen.add(record.backend_job_id)
            jobs.append(record)
        log.info(
            "Reconciling backend status for %d job(s) (%d active, %d recent terminal)",
            len(jobs),
            len(active),
            len(recent_terminal),
        )
        for record in jobs:
            await self._emit(record.backend_job_id, record.status)

    async def handle_cancel(self, backend_job_id: str) -> None:
        rec = self._db.get_by_backend_id(backend_job_id)
        if rec is None:
            log.warning(
                "Cancel ignored; job not found %s",
                job_context(job_id=backend_job_id, event="cancel"),
            )
            return
        if rec.status in TERMINAL_STATUSES:
            log.info(
                "Cancel ignored; job already terminal %s status=%s",
                job_context(job_id=backend_job_id, event="cancel"),
                rec.status.value,
            )
            return
        if rec.cups_job_id:
            try:
                await self._printer.cancel(rec.cups_job_id)
            except PrinterError as e:
                log.warning(
                    "CUPS cancel failed %s error=%s",
                    job_context(
                        job_id=backend_job_id,
                        cups_job_id=rec.cups_job_id,
                        event="cancel",
                    ),
                    e,
                )
        try:
            self._db.update_status(backend_job_id, JobStatus.CANCELLED)
        except InvalidTransitionError:
            pass
        await self._emit(backend_job_id, JobStatus.CANCELLED)
        log.info(
            "Job cancelled %s",
            job_context(job_id=backend_job_id, event="cancelled", status="CANCELLED"),
        )

    async def _worker_loop(self) -> None:
        while not self._shutdown:
            job = await self._queue.get()
            try:
                await self.handle_assigned(job)
            except Exception:
                log.exception("Unhandled error processing job=%s", job.backend_job_id)
            finally:
                self._queue.task_done()

    def set_state_change_callback(self, callback: StateChangeCallback | None) -> None:
        self._on_state_change = callback

    async def _continue_from_downloading(
        self, job: AssignedJob, record: JobRecord
    ) -> None:
        await self._run_download_pipeline(job, record, already_downloading=True)

    async def _process_new_job(self, job: AssignedJob, record: JobRecord) -> None:
        await self._run_download_pipeline(job, record, already_downloading=False)

    async def _run_download_pipeline(
        self,
        job: AssignedJob,
        record: JobRecord,
        already_downloading: bool,
    ) -> None:
        if record.cups_job_id:
            log.error(
                "Refusing download pipeline for job with cups_job_id job=%s",
                job.backend_job_id,
            )
            await self._fail_job(
                job.backend_job_id,
                "Job already submitted to printer; refusing duplicate print",
            )
            return
        try:
            validate_print_settings(job.print_settings)
        except ValueError as e:
            await self._fail_job(job.backend_job_id, str(e))
            return

        try:
            if not already_downloading and record.status == JobStatus.RECEIVED:
                log.info(
                    "Download started %s",
                    job_context(job_id=job.backend_job_id, event="download_started"),
                )
                await self._transition(job.backend_job_id, JobStatus.DOWNLOADING)
            elif record.status == JobStatus.RETRY_WAITING:
                await self._transition(job.backend_job_id, JobStatus.DOWNLOADING)

            path = await self._downloader.download(
                job.file_url, job.backend_job_id, job.filename
            )
            log.info(
                "Download completed %s",
                job_context(job_id=job.backend_job_id, event="download_completed"),
            )
            processing_path = self._move_to_processing(path, job.backend_job_id)
            self._db.set_file_path(job.backend_job_id, str(processing_path))
            log.info(
                "Job ready %s",
                job_context(job_id=job.backend_job_id, event="ready", status="READY"),
            )
            await self._transition(job.backend_job_id, JobStatus.READY)
            await self._submit_and_monitor(job, processing_path)
        except DownloadError as e:
            await self._handle_pre_submit_failure(
                job, e, classify_download_error(e)
            )
        except PrinterError as e:
            await self._handle_pre_submit_failure(
                job, e, classify_printer_error(e)
            )
        except OSError as e:
            await self._handle_pre_submit_failure(job, e, FailureKind.PERMANENT)
        except Exception as e:
            log.exception("Unexpected job failure job=%s", job.backend_job_id)
            await self._fail_job(job.backend_job_id, str(e))

    async def _handle_pre_submit_failure(
        self,
        job: AssignedJob,
        exc: Exception,
        kind: FailureKind,
    ) -> None:
        backend_job_id = job.backend_job_id
        rec = self._db.get_by_backend_id(backend_job_id)
        if rec and rec.cups_job_id:
            await self._fail_job(
                backend_job_id,
                "Failure after printer submission; requires reconciliation",
            )
            return
        if kind == FailureKind.RETRYABLE:
            self._db.increment_attempt(backend_job_id)
            rec = self._db.get_by_backend_id(backend_job_id)
            if rec and rec.attempt_count >= self._retry_policy.max_attempts:
                await self._fail_job(
                    backend_job_id,
                    f"Max retry attempts ({self._retry_policy.max_attempts}) exceeded: {exc}",
                )
                return
            await self._schedule_retry(backend_job_id, str(exc))
            rec = self._db.get_by_backend_id(backend_job_id)
            if rec and rec.status == JobStatus.RETRY_WAITING:
                await self._retry_from_waiting(job, rec)
            return
        await self._fail_job(backend_job_id, str(exc))

    async def _schedule_retry(self, backend_job_id: str, message: str) -> None:
        rec = self._db.get_by_backend_id(backend_job_id)
        attempt = rec.attempt_count if rec else 1
        delay = self._retry_policy.delay_for_attempt(attempt)
        next_at = datetime.now(UTC).timestamp() + delay
        self._db.merge_metadata(
            backend_job_id,
            {"next_retry_at": datetime.fromtimestamp(next_at, tz=UTC).isoformat()},
        )
        log.warning(
            "Scheduling retry job=%s attempt=%s delay=%.1fs: %s",
            backend_job_id,
            attempt,
            delay,
            message,
        )
        try:
            self._db.update_status(
                backend_job_id,
                JobStatus.RETRY_WAITING,
                error_message=message,
            )
        except InvalidTransitionError:
            pass
        await self._emit(backend_job_id, JobStatus.RETRY_WAITING, extra={"error": message})

    async def _retry_from_waiting(self, job: AssignedJob, record: JobRecord) -> None:
        if record.cups_job_id:
            await self._fail_job(
                record.backend_job_id,
                "RETRY_WAITING with cups_job_id; refusing duplicate print",
            )
            return
        meta = record.metadata_dict()
        next_retry = meta.get("next_retry_at")
        if isinstance(next_retry, str):
            try:
                target = datetime.fromisoformat(next_retry.replace("Z", "+00:00"))
                now = datetime.now(UTC)
                wait = (target - now).total_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)
            except ValueError:
                pass
        if record.attempt_count >= self._retry_policy.max_attempts:
            await self._fail_job(
                record.backend_job_id,
                f"Max retry attempts ({self._retry_policy.max_attempts}) exceeded",
            )
            return
        await self._run_download_pipeline(job, record, already_downloading=False)

    async def _resume_job(self, job: AssignedJob, record: JobRecord) -> None:
        status = record.status
        log.info(
            "Resuming job job=%s status=%s",
            record.backend_job_id,
            status.value,
        )

        if status == JobStatus.RECEIVED:
            await self._process_new_job(job, record)
            return

        if status == JobStatus.DOWNLOADING:
            await self._continue_from_downloading(job, record)
            return

        if status == JobStatus.RETRY_WAITING:
            await self._retry_from_waiting(job, record)
            return

        if status == JobStatus.READY:
            path = Path(record.file_path) if record.file_path else None
            if path is None or not path.is_file():
                await self._fail_job(
                    record.backend_job_id,
                    "READY job missing local file; requires backend reconciliation",
                )
                return
            await self._resume_ready_job(job, record, path)
            return

        if status in (JobStatus.SUBMITTED, JobStatus.PRINTING):
            if not record.cups_job_id:
                await self._fail_job(
                    record.backend_job_id,
                    "SUBMITTED/PRINTING without cups_job_id; refusing duplicate print",
                )
                return
            path = Path(record.file_path) if record.file_path else None
            if path is None or not path.is_file():
                await self._monitor_printer_only(record.backend_job_id, record.cups_job_id)
                return
            await self._monitor_printer(record.backend_job_id, record.cups_job_id, path)
            return

    async def _resume_ready_job(
        self, job: AssignedJob, record: JobRecord, file_path: Path
    ) -> None:
        backend_job_id = job.backend_job_id
        if record.cups_job_id:
            log.info(
                "READY with existing printer job id; monitoring only job=%s printer_job_id=%s",
                backend_job_id,
                record.cups_job_id,
            )
            await self._monitor_existing_submission(
                backend_job_id, record.cups_job_id, file_path
            )
            return

        lookup = await self._printer.find_existing_job(backend_job_id)
        if lookup.status == ExistingJobLookupStatus.FOUND and lookup.printer_job_id:
            log.info(
                "Adopting existing CUPS job for READY recovery job=%s printer_job_id=%s",
                backend_job_id,
                lookup.printer_job_id,
            )
            self._db.set_cups_job_id(backend_job_id, lookup.printer_job_id)
            await self._monitor_existing_submission(
                backend_job_id, lookup.printer_job_id, file_path
            )
            return
        if lookup.status in (
            ExistingJobLookupStatus.AMBIGUOUS,
            ExistingJobLookupStatus.LOOKUP_FAILED,
        ):
            await self._fail_job(
                backend_job_id,
                lookup.message
                or "Could not determine existing CUPS job; reconciliation required",
            )
            return

        await self._submit_and_monitor(job, file_path)

    async def _monitor_existing_submission(
        self,
        backend_job_id: str,
        printer_job_id: str,
        file_path: Path | None,
    ) -> None:
        rec = self._db.get_by_backend_id(backend_job_id)
        if rec and rec.status == JobStatus.READY:
            await self._transition(backend_job_id, JobStatus.SUBMITTED)
        if file_path is not None and file_path.is_file():
            await self._monitor_printer(backend_job_id, printer_job_id, file_path)
        else:
            await self._monitor_printer_only(backend_job_id, printer_job_id)

    async def _submit_and_monitor(self, job: AssignedJob, file_path: Path) -> None:
        log.info(
            "Submitting print job %s",
            job_context(job_id=job.backend_job_id, event="print_submit"),
        )
        try:
            result = await self._printer.submit(
                file_path, job.backend_job_id, job.print_settings
            )
        except PrinterError as e:
            kind = classify_printer_error(e)
            rec = self._db.get_by_backend_id(job.backend_job_id)
            if rec and rec.cups_job_id:
                await self._fail_job(
                    job.backend_job_id,
                    "Failure after printer submission; requires reconciliation",
                )
                return
            if kind == FailureKind.RETRYABLE:
                await self._handle_pre_submit_failure(job, e, kind)
                return
            await self._fail_job(job.backend_job_id, str(e))
            return
        log.info(
            "CUPS job created %s",
            job_context(
                job_id=job.backend_job_id,
                cups_job_id=result.printer_job_id,
                event="cups_job_created",
                status="SUBMITTED",
            ),
        )
        self._db.set_cups_job_id(job.backend_job_id, result.printer_job_id)
        await self._transition(job.backend_job_id, JobStatus.SUBMITTED)
        await self._monitor_printer(
            job.backend_job_id, result.printer_job_id, file_path
        )

    async def _monitor_printer(
        self, backend_job_id: str, printer_job_id: str, file_path: Path
    ) -> None:
        while True:
            status = await self._printer.get_status(printer_job_id)
            if await self._process_printer_poll_status(
                backend_job_id, printer_job_id, status, file_path
            ):
                return
            await asyncio.sleep(self._poll_interval)

    async def _monitor_printer_only(
        self, backend_job_id: str, printer_job_id: str
    ) -> None:
        while True:
            status = await self._printer.get_status(printer_job_id)
            if await self._process_printer_poll_status(
                backend_job_id, printer_job_id, status, None
            ):
                return
            await asyncio.sleep(self._poll_interval)

    async def _process_printer_poll_status(
        self,
        backend_job_id: str,
        printer_job_id: str,
        status: PrinterJobStatus,
        file_path: Path | None,
    ) -> bool:
        """Handle one printer poll. Returns True when monitoring should stop."""
        if status.state == PrinterJobState.UNKNOWN:
            log.debug(
                "CUPS state temporarily unavailable %s",
                job_context(job_id=backend_job_id, cups_job_id=printer_job_id),
            )
            return False

        if status.state == PrinterJobState.FAILED:
            await self._fail_job(
                backend_job_id, status.message or "Printer reported failure"
            )
            return True

        if status.state == PrinterJobState.CANCELLED:
            await self._fail_job(
                backend_job_id,
                status.message or "Printer job canceled or aborted",
            )
            return True

        if status.state == PrinterJobState.PENDING:
            return False

        if status.state == PrinterJobState.PRINTING:
            rec = self._db.get_by_backend_id(backend_job_id)
            if rec and rec.status != JobStatus.PRINTING:
                log.info(
                    "Printing started %s",
                    job_context(
                        job_id=backend_job_id,
                        cups_job_id=printer_job_id,
                        event="printing",
                        status="PRINTING",
                    ),
                )
                await self._transition(backend_job_id, JobStatus.PRINTING)
            return False

        if status.state == PrinterJobState.COMPLETED:
            log.info(
                "Print completed %s",
                job_context(
                    job_id=backend_job_id,
                    cups_job_id=printer_job_id,
                    event="completed",
                ),
            )
            if file_path is not None and file_path.is_file():
                await self._complete_job(backend_job_id, file_path)
            else:
                rec = self._db.get_by_backend_id(backend_job_id)
                path = Path(rec.file_path) if rec and rec.file_path else None
                if path and path.is_file():
                    await self._complete_job(backend_job_id, path)
                else:
                    await self._transition(backend_job_id, JobStatus.COMPLETED)
            return True

        return False

    async def _complete_job(self, backend_job_id: str, file_path: Path) -> None:
        dest = self._completed_dir / file_path.name
        if file_path.exists():
            shutil.move(str(file_path), dest)
        await self._transition(backend_job_id, JobStatus.COMPLETED)

    async def _fail_job(self, backend_job_id: str, message: str) -> None:
        rec_for_log = self._db.get_by_backend_id(backend_job_id)
        cups_id = rec_for_log.cups_job_id if rec_for_log else None
        log.error(
            "Print failed %s reason=%s",
            job_context(
                job_id=backend_job_id,
                cups_job_id=cups_id,
                event="failed",
                status="FAILED",
            ),
            message,
        )
        rec = self._db.get_by_backend_id(backend_job_id)
        if rec and rec.file_path:
            src = Path(rec.file_path)
            if src.is_file():
                dest = self._failed_dir / src.name
                try:
                    shutil.move(str(src), dest)
                except OSError:
                    pass
        try:
            self._db.update_status(backend_job_id, JobStatus.FAILED, message)
        except InvalidTransitionError:
            pass
        await self._emit(backend_job_id, JobStatus.FAILED, extra={"error": message})

    async def _transition(
        self, backend_job_id: str, new_status: JobStatus, **extra: Any
    ) -> None:
        self._db.update_status(backend_job_id, new_status)
        await self._emit(backend_job_id, new_status, extra=extra)

    async def _emit(
        self,
        backend_job_id: str,
        status: JobStatus,
        extra: dict[str, Any] | None = None,
    ) -> None:
        log.info(
            "Job state %s",
            job_context(job_id=backend_job_id, status=status.value, event="state"),
        )
        if self._on_state_change:
            payload = dict(extra or {})
            rec = self._db.get_by_backend_id(backend_job_id)
            if rec and rec.cups_job_id and "cups_job_id" not in payload:
                payload["cups_job_id"] = rec.cups_job_id
            await self._on_state_change(backend_job_id, status, payload)

    def _move_to_processing(self, path: Path, backend_job_id: str) -> Path:
        dest = self._processing_dir / path.name
        shutil.move(str(path), dest)
        return dest

    def _cleanup_stale_part_files(self, incoming_dir: Path) -> None:
        cutoff = time.time() - 86400
        for part in incoming_dir.glob("*.part"):
            try:
                if part.stat().st_mtime < cutoff:
                    part.unlink()
                    log.info("Removed stale partial download %s", part.name)
            except OSError:
                pass

    def _record_to_assigned(self, record: JobRecord) -> AssignedJob | None:
        meta = record.metadata_dict()
        settings_raw = meta.get("print_settings") or {}
        from app.models import PrintSettings

        file_url = meta.get("file_url")
        if not isinstance(file_url, str):
            file_url = ""
        return AssignedJob(
            backend_job_id=record.backend_job_id,
            file_url=file_url,
            filename=meta.get("filename"),
            print_settings=PrintSettings.from_dict(settings_raw),
        )

    def non_terminal_job_count(self) -> int:
        return len(self._db.list_non_terminal_jobs())

    def current_job_id(self) -> str | None:
        jobs = self._db.list_non_terminal_jobs()
        if not jobs:
            return None
        return jobs[0].backend_job_id
