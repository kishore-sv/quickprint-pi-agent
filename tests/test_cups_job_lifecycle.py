"""CUPS post-submission job lifecycle tests."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path

import pytest

from app.cups import CupsPrinter
from app.cups_command import CommandResult
from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.models import AssignedJob, JobStatus, PrintSettings
from tests.fake_cups_runner import FakeCupsRunner


def _cups_job_manager(
    tmp_job_dirs: dict[str, Path],
    db_path: Path,
    runner: FakeCupsRunner,
    *,
    printer_name: str = "quickprint-test",
) -> tuple[JobManager, object]:
    db = init_db(db_path)
    printer = CupsPrinter(printer_name, runner=runner)
    jm = JobManager(
        db=db,
        downloader=Downloader(tmp_job_dirs["incoming"], 1_000_000, 5),
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
    )
    jm.start()
    return jm, db


def _ready_job(db, tmp_job_dirs: dict[str, Path], backend_job_id: str) -> Path:
    file_path = tmp_job_dirs["processing"] / f"{backend_job_id}_doc.pdf"
    file_path.write_bytes(b"%PDF")
    meta = {
        "filename": "doc.pdf",
        "file_url": "http://example.com/x.pdf",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job(backend_job_id, meta)
    db.set_file_path(backend_job_id, str(file_path))
    db.update_status(backend_job_id, JobStatus.DOWNLOADING)
    db.update_status(backend_job_id, JobStatus.READY)
    return file_path


def _base_runner(printer_name: str = "quickprint-test") -> FakeCupsRunner:
    runner = FakeCupsRunner()
    runner.responses[("lpstat", "-p", printer_name)] = CommandResult(
        0, f"printer {printer_name} is idle", ""
    )
    runner.responses[("lpstat", "-r")] = CommandResult(0, "scheduler is running", "")
    return runner


@pytest.mark.asyncio
async def test_submit_unknown_then_processing_then_completed(tmp_path, tmp_job_dirs):
    backend_job_id = "lifecycle-complete"
    printer_name = "quickprint-test"
    cups_job_id = "quickprint-test-2"
    runner = _base_runner(printer_name)
    poll_counts: dict[str, int] = defaultdict(int)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, f"request id is {cups_job_id}", "")
        if args == ["lpstat", "-o", printer_name]:
            poll_counts["active"] += 1
            if poll_counts["active"] <= 2:
                return CommandResult(0, "", "")
            if poll_counts["active"] <= 4:
                return CommandResult(0, f"{cups_job_id} user processing", "")
            return CommandResult(0, "", "")
        if args == ["lpstat", "-W", "completed", "-o", printer_name]:
            return CommandResult(0, f"{cups_job_id} user completed", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", "missing"))

    runner.run = flex  # type: ignore[method-assign]
    jm, db = _cups_job_manager(tmp_job_dirs, tmp_path / "agent.db", runner)
    file_path = _ready_job(db, tmp_job_dirs, backend_job_id)
    job = AssignedJob(
        backend_job_id=backend_job_id,
        file_url="http://example.com/x.pdf",
        filename="doc.pdf",
    )

    await jm._submit_and_monitor(job, file_path)

    rec = db.get_by_backend_id(backend_job_id)
    assert rec is not None
    assert rec.status == JobStatus.COMPLETED
    assert rec.cups_job_id == cups_job_id
    assert runner.lp_call_count == 1
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_immediate_unknown_does_not_fail_job(tmp_path, tmp_job_dirs):
    backend_job_id = "lifecycle-unknown"
    printer_name = "quickprint-test"
    cups_job_id = "quickprint-test-9"
    runner = _base_runner(printer_name)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, f"request id is {cups_job_id}", "")
        if args == ["lpstat", "-o", printer_name]:
            return CommandResult(0, "", "")
        if args == ["lpstat", "-W", "completed", "-o", printer_name]:
            return CommandResult(0, "", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", "missing"))

    runner.run = flex  # type: ignore[method-assign]
    jm, db = _cups_job_manager(tmp_job_dirs, tmp_path / "agent.db", runner)
    file_path = _ready_job(db, tmp_job_dirs, backend_job_id)
    job = AssignedJob(
        backend_job_id=backend_job_id,
        file_url="http://example.com/x.pdf",
        filename="doc.pdf",
    )

    monitor_task = asyncio.create_task(jm._submit_and_monitor(job, file_path))
    await asyncio.sleep(0.15)
    rec = db.get_by_backend_id(backend_job_id)
    assert rec is not None
    assert rec.status == JobStatus.SUBMITTED
    assert rec.cups_job_id == cups_job_id
    assert runner.lp_call_count == 1
    monitor_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await monitor_task
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_unknown_never_causes_duplicate_lp_submission(tmp_path, tmp_job_dirs):
    backend_job_id = "lifecycle-no-dup"
    printer_name = "quickprint-test"
    cups_job_id = "quickprint-test-3"
    runner = _base_runner(printer_name)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, f"request id is {cups_job_id}", "")
        if args == ["lpstat", "-o", printer_name]:
            return CommandResult(0, "", "")
        if args == ["lpstat", "-W", "completed", "-o", printer_name]:
            return CommandResult(0, "", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", "missing"))

    runner.run = flex  # type: ignore[method-assign]
    jm, db = _cups_job_manager(tmp_job_dirs, tmp_path / "agent.db", runner)
    file_path = _ready_job(db, tmp_job_dirs, backend_job_id)
    db.set_cups_job_id(backend_job_id, cups_job_id)
    db.update_status(backend_job_id, JobStatus.SUBMITTED)

    recover_task = asyncio.create_task(jm.recover_unfinished_jobs())
    await asyncio.sleep(0.15)
    assert runner.lp_call_count == 0
    recover_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await recover_task
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_canceled_and_aborted_transition_to_failed(tmp_path, tmp_job_dirs):
    printer_name = "quickprint-test"
    runner = _base_runner(printer_name)
    jm, db = _cups_job_manager(tmp_job_dirs, tmp_path / "agent.db", runner)

    for backend_job_id, line in (
        ("lifecycle-canceled", "quickprint-test-4 user canceled"),
        ("lifecycle-aborted", "quickprint-test-5 user aborted"),
    ):
        cups_job_id = line.split()[0]
        runner.responses[("lpstat", "-o", printer_name)] = CommandResult(0, line, "")
        runner.responses[("lpstat", "-W", "completed", "-o", printer_name)] = (
            CommandResult(0, "", "")
        )
        file_path = _ready_job(db, tmp_job_dirs, backend_job_id)
        db.set_cups_job_id(backend_job_id, cups_job_id)
        db.update_status(backend_job_id, JobStatus.SUBMITTED)
        await jm._monitor_printer(backend_job_id, cups_job_id, file_path)
        rec = db.get_by_backend_id(backend_job_id)
        assert rec is not None
        assert rec.status == JobStatus.FAILED

    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_recovery_with_existing_cups_job_id_does_not_resubmit(
    tmp_path, tmp_job_dirs
):
    backend_job_id = "lifecycle-recover"
    printer_name = "quickprint-test"
    cups_job_id = "quickprint-test-6"
    runner = _base_runner(printer_name)
    poll_counts: dict[str, int] = defaultdict(int)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, f"request id is {cups_job_id}", "")
        if args == ["lpstat", "-o", printer_name]:
            poll_counts["active"] += 1
            if poll_counts["active"] <= 1:
                return CommandResult(0, "", "")
            if poll_counts["active"] <= 3:
                return CommandResult(0, f"{cups_job_id} user processing", "")
            return CommandResult(0, "", "")
        if args == ["lpstat", "-W", "completed", "-o", printer_name]:
            return CommandResult(0, f"{cups_job_id} user completed", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", "missing"))

    runner.run = flex  # type: ignore[method-assign]
    db_path = tmp_path / "agent.db"
    jm, db = _cups_job_manager(tmp_job_dirs, db_path, runner)
    file_path = _ready_job(db, tmp_job_dirs, backend_job_id)
    db.set_cups_job_id(backend_job_id, cups_job_id)
    db.update_status(backend_job_id, JobStatus.SUBMITTED)

    await jm.recover_unfinished_jobs()
    for _ in range(100):
        rec = db.get_by_backend_id(backend_job_id)
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    rec = db.get_by_backend_id(backend_job_id)
    assert rec is not None
    assert rec.status == JobStatus.COMPLETED
    assert runner.lp_call_count == 0
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_completed_job_detected_from_completed_queue(tmp_path, tmp_job_dirs):
    backend_job_id = "lifecycle-completed-queue"
    printer_name = "quickprint-test"
    cups_job_id = "quickprint-test-7"
    runner = _base_runner(printer_name)
    runner.responses[("lpstat", "-o", printer_name)] = CommandResult(0, "", "")
    runner.responses[("lpstat", "-W", "completed", "-o", printer_name)] = CommandResult(
        0, f"{cups_job_id} user completed", ""
    )

    jm, db = _cups_job_manager(tmp_job_dirs, tmp_path / "agent.db", runner)
    file_path = _ready_job(db, tmp_job_dirs, backend_job_id)
    db.set_cups_job_id(backend_job_id, cups_job_id)
    db.update_status(backend_job_id, JobStatus.SUBMITTED)

    await jm._monitor_printer(backend_job_id, cups_job_id, file_path)

    rec = db.get_by_backend_id(backend_job_id)
    assert rec is not None
    assert rec.status == JobStatus.COMPLETED
    assert not file_path.exists()
    await jm.stop()
    db.close()
