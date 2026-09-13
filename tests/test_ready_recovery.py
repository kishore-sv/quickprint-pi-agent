"""Regression tests for READY-state duplicate-print recovery."""

import asyncio

import pytest

from app.cups import CupsPrinter
from app.cups_command import CommandResult
from app.cups_job_identity import cups_job_title
from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.mock_printer import MockPrinter
from app.models import AssignedJob, JobStatus, PrintSettings
from tests.fake_cups_runner import FakeCupsRunner


def _cups_printer_with_runner() -> tuple[CupsPrinter, FakeCupsRunner]:
    runner = FakeCupsRunner()
    runner.responses[("lpstat", "-p", "PiPrinter")] = CommandResult(
        0, "printer PiPrinter is idle", ""
    )
    runner.responses[("lpstat", "-r")] = CommandResult(0, "scheduler is running", "")
    return CupsPrinter("PiPrinter", runner=runner), runner


@pytest.mark.asyncio
async def test_ready_with_cups_job_id_does_not_resubmit(tmp_path, tmp_job_dirs):
    db = init_db(tmp_path / "agent.db")
    from app.mock_printer import _MockJob

    printer = MockPrinter(delay_seconds=0.05)
    file_path = tmp_job_dirs["processing"] / "job-ready_doc.pdf"
    file_path.write_bytes(b"%PDF")
    printer.submit_count = 1
    printer._jobs["mock-existing"] = _MockJob(
        backend_job_id="job-ready",
        file_path=file_path,
        submitted_at=0.0,
        delay_seconds=0.05,
        simulate_failure=False,
    )

    meta = {
        "filename": "doc.pdf",
        "file_url": "http://example.com/x.pdf",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job("job-ready", meta)
    db.set_file_path("job-ready", str(file_path))
    db.update_status("job-ready", JobStatus.DOWNLOADING)
    db.update_status("job-ready", JobStatus.READY)
    db.set_cups_job_id("job-ready", "mock-existing")

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
    await jm.recover_unfinished_jobs()
    for _ in range(80):
        rec = db.get_by_backend_id("job-ready")
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    assert printer.submit_count == 1
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_cups_accepted_persisted_id_restart_monitored(tmp_path, tmp_job_dirs):
    db_path = tmp_path / "agent.db"
    db = init_db(db_path)
    printer, runner = _cups_printer_with_runner()

    async def flex(args, timeout):
        if args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, "request id is PiPrinter-10", "")
        key = tuple(args)
        if key in runner.responses:
            return runner.responses[key]
        if args[:2] == ["lpstat", "-o"] and len(args) == 2:
            return CommandResult(0, "PiPrinter-10 user processing", "")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(1, "", "")
        return CommandResult(1, "", "missing")

    runner.run = flex  # type: ignore[method-assign]

    file_path = tmp_job_dirs["processing"] / "job-a_doc.pdf"
    file_path.write_bytes(b"%PDF")
    meta = {"filename": "doc.pdf", "file_url": "http://x", "print_settings": {}}
    db.create_job("job-a", meta)
    db.set_file_path("job-a", str(file_path))
    db.update_status("job-a", JobStatus.DOWNLOADING)
    db.update_status("job-a", JobStatus.READY)
    db.set_cups_job_id("job-a", "PiPrinter-10")
    db.update_status("job-a", JobStatus.SUBMITTED)

    jm = JobManager(
        db=db,
        downloader=Downloader(tmp_job_dirs["incoming"], 1_000, 5),
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
    )
    jm.start()

    async def complete_later():
        await asyncio.sleep(0.05)
        runner.responses[("lpstat", "-o", "PiPrinter-10")] = CommandResult(1, "", "")
        runner.responses[("lpstat", "-W", "completed", "-o", "PiPrinter-10")] = (
            CommandResult(0, "PiPrinter-10 completed", "")
        )

    asyncio.create_task(complete_later())
    await jm.recover_unfinished_jobs()
    for _ in range(80):
        rec = db.get_by_backend_id("job-a")
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    assert runner.lp_call_count == 0
    await jm.stop()

    db2 = init_db(db_path)
    printer2, runner2 = _cups_printer_with_runner()
    runner2.run = flex  # type: ignore[method-assign]
    jm2 = JobManager(
        db=db2,
        downloader=Downloader(tmp_job_dirs["incoming"], 1_000, 5),
        printer=printer2,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
    )
    jm2.start()
    await jm2.recover_unfinished_jobs()
    assert runner2.lp_call_count == 0
    await jm2.stop()
    db2.close()
    db.close()


@pytest.mark.asyncio
async def test_ready_adopts_existing_cups_job_by_title(tmp_path, tmp_job_dirs):
    backend_job_id = "orphan-ready-001"
    title = cups_job_title(backend_job_id)
    db = init_db(tmp_path / "agent.db")
    printer, runner = _cups_printer_with_runner()

    async def flex(args, timeout):
        if args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, "request id is PiPrinter-55", "")
        key = tuple(args)
        if key in runner.responses:
            return runner.responses[key]
        if args == ["lpstat", "-o"]:
            return CommandResult(0, f"PiPrinter-55 user 1024 {title}", "")
        if args == ["lpstat", "-l", "-o", "PiPrinter-55"]:
            return CommandResult(0, f"Title: {title}", "")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(1, "", "")
        if args[:2] == ["lpstat", "-o"] and len(args) == 3:
            return CommandResult(0, "PiPrinter-55 user processing", "")
        return CommandResult(1, "", "missing")

    runner.run = flex  # type: ignore[method-assign]

    file_path = tmp_job_dirs["processing"] / f"{backend_job_id}_doc.pdf"
    file_path.write_bytes(b"%PDF")
    meta = {
        "filename": "doc.pdf",
        "file_url": "http://x",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job(backend_job_id, meta)
    db.set_file_path(backend_job_id, str(file_path))
    db.update_status(backend_job_id, JobStatus.DOWNLOADING)
    db.update_status(backend_job_id, JobStatus.READY)

    jm = JobManager(
        db=db,
        downloader=Downloader(tmp_job_dirs["incoming"], 1_000, 5),
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
    )
    jm.start()

    async def complete_later():
        await asyncio.sleep(0.08)
        runner.responses[("lpstat", "-o", "PiPrinter-55")] = CommandResult(1, "", "")
        runner.responses[("lpstat", "-W", "completed", "-o", "PiPrinter-55")] = (
            CommandResult(0, "PiPrinter-55 completed", "")
        )

    asyncio.create_task(complete_later())
    await jm.recover_unfinished_jobs()
    for _ in range(100):
        rec = db.get_by_backend_id(backend_job_id)
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    rec = db.get_by_backend_id(backend_job_id)
    assert rec is not None
    assert rec.cups_job_id == "PiPrinter-55"
    assert runner.lp_call_count == 0
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_ready_lookup_failure_fails_safe(tmp_path, tmp_job_dirs):
    db = init_db(tmp_path / "agent.db")
    printer, runner = _cups_printer_with_runner()

    async def fail_list(args, timeout):
        if args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, "request id is PiPrinter-1", "")
        return CommandResult(1, "", "lpstat failed")

    runner.run = fail_list  # type: ignore[method-assign]

    file_path = tmp_job_dirs["processing"] / "job-fail_doc.pdf"
    file_path.write_bytes(b"%PDF")
    meta = {"filename": "doc.pdf", "file_url": "http://x", "print_settings": {}}
    db.create_job("job-fail", meta)
    db.set_file_path("job-fail", str(file_path))
    db.update_status("job-fail", JobStatus.DOWNLOADING)
    db.update_status("job-fail", JobStatus.READY)

    jm = JobManager(
        db=db,
        downloader=Downloader(tmp_job_dirs["incoming"], 1_000, 5),
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
    )
    jm.start()
    await jm.recover_unfinished_jobs()
    await asyncio.sleep(0.1)
    rec = db.get_by_backend_id("job-fail")
    assert rec is not None
    assert rec.status == JobStatus.FAILED
    assert runner.lp_call_count == 0
    await jm.stop()
    db.close()
