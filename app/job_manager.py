"""Orchestrates print job lifecycle."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.database import Database
from app.downloader import Downloader, DownloadError
from app.logger import get_logger
from app.models import (
    AssignedJob,
    JobRecord,
    JobStatus,
    TERMINAL_STATUSES,
    InvalidTransitionError,
)
from app.printer import Printer, PrinterError, PrinterJobState

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
        on_state_change: StateChangeCallback | None = None,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        self._db = db
        self._downloader = downloader
        self._printer = printer
        self._processing_dir = processing_dir
        self._completed_dir = completed_dir
        self._failed_dir = failed_dir
        self._on_state_change = on_state_change
        self._poll_interval = poll_interval_seconds
        self._queue: asyncio.Queue[AssignedJob] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._shutdown = False

    def start(self) -> None:
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
        try:
            path = await self._downloader.download(
                job.file_url, job.backend_job_id, job.filename
            )
            processing_path = self._move_to_processing(path, job.backend_job_id)
            self._db.set_file_path(job.backend_job_id, str(processing_path))
            await self._transition(job.backend_job_id, JobStatus.READY)
            await self._submit_and_monitor(job, processing_path)
        except (DownloadError, PrinterError, OSError) as e:
            await self._fail_job(job.backend_job_id, str(e))

    async def _process_new_job(self, job: AssignedJob, record: JobRecord) -> None:
        try:
            if record.status == JobStatus.RECEIVED:
                await self._transition(job.backend_job_id, JobStatus.DOWNLOADING)
            path = await self._downloader.download(
                job.file_url, job.backend_job_id, job.filename
            )
            processing_path = self._move_to_processing(path, job.backend_job_id)
            self._db.set_file_path(job.backend_job_id, str(processing_path))
            await self._transition(job.backend_job_id, JobStatus.READY)
            await self._submit_and_monitor(job, processing_path)
        except (DownloadError, PrinterError, OSError) as e:
            await self._fail_job(job.backend_job_id, str(e))
        except Exception as e:
            log.exception("Unexpected job failure job=%s", job.backend_job_id)
            await self._fail_job(job.backend_job_id, str(e))

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

        if status == JobStatus.READY:
            path = Path(record.file_path) if record.file_path else None
            if path is None or not path.is_file():
                await self._fail_job(
                    record.backend_job_id,
                    "READY job missing local file; requires backend reconciliation",
                )
                return
            await self._submit_and_monitor(job, path)
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

        if status == JobStatus.RETRY_WAITING:
            await self._process_new_job(job, record)

    async def _submit_and_monitor(self, job: AssignedJob, file_path: Path) -> None:
        result = await self._printer.submit(
            file_path, job.backend_job_id, job.print_settings
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
            if status.state == PrinterJobState.UNKNOWN:
                await self._fail_job(
                    backend_job_id,
                    status.message
                    or "Printer state unknown; refusing duplicate print",
                )
                return
            if status.state == PrinterJobState.FAILED:
                await self._fail_job(
                    backend_job_id, status.message or "Printer reported failure"
                )
                return
            if status.state == PrinterJobState.CANCELLED:
                await self._transition(backend_job_id, JobStatus.CANCELLED)
                return
            if status.state == PrinterJobState.PENDING:
                pass
            elif status.state == PrinterJobState.PRINTING:
                rec = self._db.get_by_backend_id(backend_job_id)
                if rec and rec.status != JobStatus.PRINTING:
                    await self._transition(backend_job_id, JobStatus.PRINTING)
            elif status.state == PrinterJobState.COMPLETED:
                await self._complete_job(backend_job_id, file_path)
                return
            await asyncio.sleep(self._poll_interval)

    async def _monitor_printer_only(
        self, backend_job_id: str, printer_job_id: str
    ) -> None:
        while True:
            status = await self._printer.get_status(printer_job_id)
            if status.state == PrinterJobState.UNKNOWN:
                await self._fail_job(
                    backend_job_id,
                    status.message
                    or "Printer state unknown; refusing duplicate print",
                )
                return
            if status.state == PrinterJobState.FAILED:
                await self._fail_job(
                    backend_job_id, status.message or "Printer reported failure"
                )
                return
            if status.state == PrinterJobState.COMPLETED:
                rec = self._db.get_by_backend_id(backend_job_id)
                path = Path(rec.file_path) if rec and rec.file_path else None
                if path and path.is_file():
                    await self._complete_job(backend_job_id, path)
                else:
                    await self._transition(backend_job_id, JobStatus.COMPLETED)
                return
            if status.state == PrinterJobState.PRINTING:
                rec = self._db.get_by_backend_id(backend_job_id)
                if rec and rec.status != JobStatus.PRINTING:
                    await self._transition(backend_job_id, JobStatus.PRINTING)
            await asyncio.sleep(self._poll_interval)

    async def _complete_job(self, backend_job_id: str, file_path: Path) -> None:
        dest = self._completed_dir / file_path.name
        if file_path.exists():
            shutil.move(str(file_path), dest)
        await self._transition(backend_job_id, JobStatus.COMPLETED)

    async def _fail_job(self, backend_job_id: str, message: str) -> None:
        log.error("Job failed job=%s: %s", backend_job_id, message)
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
        log.info("Job state job=%s status=%s", backend_job_id, status.value)
        if self._on_state_change:
            payload = extra or {}
            await self._on_state_change(backend_job_id, status, payload)

    def _move_to_processing(self, path: Path, backend_job_id: str) -> Path:
        dest = self._processing_dir / path.name
        shutil.move(str(path), dest)
        return dest

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
