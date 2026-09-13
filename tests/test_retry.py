import asyncio

import pytest

from app.database import init_db
from app.downloader import Downloader, RetryableDownloadError
from app.job_manager import JobManager
from app.mock_printer import MockPrinter
from app.models import AssignedJob, JobStatus
from app.retry import RetryPolicy
from tests.conftest import make_job_manager


class FlakyDownloader(Downloader):
    def __init__(self, *args, fail_times: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self._fail_times = fail_times
        self._calls = 0

    async def download(self, url, backend_job_id, filename_hint=None):
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RetryableDownloadError("temporary network error")
        return await super().download(url, backend_job_id, filename_hint)


@pytest.mark.asyncio
async def test_retryable_download_then_success(db, tmp_job_dirs, http_server):
    printer = MockPrinter(delay_seconds=0.05)
    flaky = FlakyDownloader(
        tmp_job_dirs["incoming"], 1_000_000, 5, fail_times=1
    )
    jm = JobManager(
        db=db,
        downloader=flaky,
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        incoming_dir=tmp_job_dirs["incoming"],
        poll_interval_seconds=0.01,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.05),
    )
    jm.start()
    job = AssignedJob(backend_job_id="retry-job", file_url=http_server, filename="a.pdf")
    await jm.handle_assigned(job)
    for _ in range(150):
        rec = db.get_by_backend_id("retry-job")
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    rec = db.get_by_backend_id("retry-job")
    assert rec is not None
    assert rec.status == JobStatus.COMPLETED
    assert printer.submit_count == 1
    await jm.stop()


@pytest.mark.asyncio
async def test_max_retries_failed(db, tmp_job_dirs):
    printer = MockPrinter(delay_seconds=0.05)
    flaky = FlakyDownloader(
        tmp_job_dirs["incoming"], 1_000_000, 5, fail_times=10
    )
    jm = JobManager(
        db=db,
        downloader=flaky,
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.01, max_delay_seconds=0.05),
    )
    jm.start()
    job = AssignedJob(
        backend_job_id="fail-job",
        file_url="http://127.0.0.1:9/nope.pdf",
        filename="a.pdf",
    )
    await jm.handle_assigned(job)
    await asyncio.sleep(0.3)
    rec = db.get_by_backend_id("fail-job")
    assert rec is not None
    assert rec.status == JobStatus.FAILED
    assert printer.submit_count == 0
    await jm.stop()
