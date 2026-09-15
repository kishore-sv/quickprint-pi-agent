"""Reconcile re-reports recently terminal jobs after WS reconnect."""

import pytest

from app.database import init_db
from app.job_manager import JobManager
from app.models import JobStatus
from tests.test_status_reporting import StatusCapture, _make_settings, make_job_manager


@pytest.mark.asyncio
async def test_reconcile_includes_recently_completed(tmp_path, tmp_job_dirs):
    settings = _make_settings(tmp_path, tmp_job_dirs)
    db = init_db(tmp_path / "reconcile.db")
    capture = StatusCapture()
    jm = make_job_manager(db, tmp_job_dirs)
    jm.set_state_change_callback(capture.callback)

    db.create_job("done-job", {"filename": "doc.pdf"})
    db.update_status("done-job", JobStatus.DOWNLOADING)
    db.update_status("done-job", JobStatus.READY)
    db.update_status("done-job", JobStatus.SUBMITTED)
    db.update_status("done-job", JobStatus.COMPLETED)

    await jm.reconcile_backend_status()

    assert capture.outbound_types()[-1] == "job.completed"
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_list_recently_terminal_jobs_excludes_old(tmp_path):
    db = init_db(tmp_path / "recent.db")
    db.create_job("fresh", {"filename": "a.pdf"})
    db.update_status("fresh", JobStatus.DOWNLOADING)
    db.update_status("fresh", JobStatus.READY)
    db.update_status("fresh", JobStatus.SUBMITTED)
    db.update_status("fresh", JobStatus.COMPLETED)

    recent = db.list_recently_terminal_jobs(within_seconds=300)
    assert len(recent) == 1
    assert recent[0].backend_job_id == "fresh"

    with db._lock:
        db._conn.execute(
            "UPDATE jobs SET updated_at = '2020-01-01T00:00:00Z' WHERE backend_job_id = ?",
            ("fresh",),
        )
        db._conn.commit()

    assert db.list_recently_terminal_jobs(within_seconds=300) == []
    db.close()
