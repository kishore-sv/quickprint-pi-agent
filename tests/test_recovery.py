"""Restart and duplicate-print protection tests."""

import asyncio

import pytest

from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.mock_printer import MockPrinter
from app.models import AssignedJob, JobStatus, PrintSettings
from tests.conftest import make_job_manager


@pytest.mark.asyncio
async def test_no_duplicate_print_after_completion(
    tmp_path, tmp_job_dirs, http_server
):
    db_path = tmp_path / "agent.db"
    db = init_db(db_path)

    printer1 = MockPrinter(delay_seconds=0.05)
    jm1 = make_job_manager(db, tmp_job_dirs, printer1)
    job = AssignedJob(
        backend_job_id="job-dup-protect",
        file_url=http_server,
        filename="doc.pdf",
        print_settings=PrintSettings(),
    )
    await jm1.handle_assigned(job)
    for _ in range(100):
        rec = db.get_by_backend_id("job-dup-protect")
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    assert printer1.submit_count == 1
    await jm1.stop()

    db2 = init_db(db_path)
    printer2 = MockPrinter(delay_seconds=0.05)
    jm2 = make_job_manager(db2, tmp_job_dirs, printer2)
    await jm2.handle_assigned(job)
    await asyncio.sleep(0.1)
    rec = db2.get_by_backend_id("job-dup-protect")
    assert rec is not None
    assert rec.status == JobStatus.COMPLETED
    assert printer2.submit_count == 0
    await jm2.stop()
    db2.close()
    db.close()


@pytest.mark.asyncio
async def test_submitted_without_printer_state_fails_safe(tmp_path, tmp_job_dirs):
    db_path = tmp_path / "agent.db"
    db = init_db(db_path)

    meta = {
        "filename": "doc.pdf",
        "file_url": "http://127.0.0.1/file.pdf",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job("job-mid", meta)
    file_path = tmp_job_dirs["processing"] / "job-mid_doc.pdf"
    file_path.write_bytes(b"%PDF-1.4")
    db.set_file_path("job-mid", str(file_path))
    db.update_status("job-mid", JobStatus.DOWNLOADING)
    db.update_status("job-mid", JobStatus.READY)
    db.set_cups_job_id("job-mid", "mock-lost-after-reboot")
    db.update_status("job-mid", JobStatus.SUBMITTED)

    printer2 = MockPrinter(delay_seconds=0.05)
    downloader = Downloader(tmp_job_dirs["incoming"], 1_000_000, 5)
    jm2 = JobManager(
        db=db,
        downloader=downloader,
        printer=printer2,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
    )
    jm2.start()
    await jm2.recover_unfinished_jobs()
    for _ in range(50):
        rec = db.get_by_backend_id("job-mid")
        if rec and rec.status == JobStatus.FAILED:
            break
        await asyncio.sleep(0.05)
    rec = db.get_by_backend_id("job-mid")
    assert rec is not None
    assert rec.status == JobStatus.FAILED
    assert printer2.submit_count == 0
    await jm2.stop()
    db.close()
