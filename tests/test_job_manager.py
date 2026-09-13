"""JobManager tests."""

import asyncio

import pytest

from app.downloader import sanitize_filename
from app.models import AssignedJob, JobStatus, PrintSettings
from tests.conftest import make_job_manager


@pytest.mark.asyncio
async def test_job_completion_happy_path(db, tmp_job_dirs, http_server):
    from app.mock_printer import MockPrinter

    printer = MockPrinter(delay_seconds=0.05)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    job = AssignedJob(
        backend_job_id="job-ok",
        file_url=http_server,
        filename="doc.pdf",
        print_settings=PrintSettings(),
    )
    await jm.handle_assigned(job)
    for _ in range(100):
        rec = db.get_by_backend_id("job-ok")
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    rec = db.get_by_backend_id("job-ok")
    assert rec is not None
    assert rec.status == JobStatus.COMPLETED
    assert printer.submit_count == 1
    await jm.stop()


@pytest.mark.asyncio
async def test_job_failure_mock_printer(db, tmp_job_dirs, http_server):
    from app.mock_printer import MockPrinter

    printer = MockPrinter(delay_seconds=0.05, simulate_failure=True)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    job = AssignedJob(
        backend_job_id="job-fail",
        file_url=http_server,
        filename="doc.pdf",
    )
    await jm.handle_assigned(job)
    for _ in range(100):
        rec = db.get_by_backend_id("job-fail")
        if rec and rec.status == JobStatus.FAILED:
            break
        await asyncio.sleep(0.05)
    rec = db.get_by_backend_id("job-fail")
    assert rec is not None
    assert rec.status == JobStatus.FAILED
    await jm.stop()


def test_filename_sanitization():
    assert sanitize_filename("../../etc/passwd") == "job.pdf"
    assert sanitize_filename("my doc.pdf") == "my_doc.pdf"
    assert sanitize_filename(None) == "job.pdf"
