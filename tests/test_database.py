"""Database tests."""

import pytest

from app.models import InvalidTransitionError, JobStatus


def test_init_and_create_job(db):
    record = db.create_job("job-1", {"filename": "a.pdf"})
    assert record.backend_job_id == "job-1"
    assert record.status == JobStatus.RECEIVED


def test_unique_backend_job_id(db):
    db.create_job("job-dup")
    second = db.create_job("job-dup")
    assert second.backend_job_id == "job-dup"
    fetched = db.get_by_backend_id("job-dup")
    assert fetched is not None
    assert fetched.id == second.id


def test_state_transitions(db):
    db.create_job("job-t")
    db.update_status("job-t", JobStatus.DOWNLOADING)
    db.update_status("job-t", JobStatus.READY)
    rec = db.get_by_backend_id("job-t")
    assert rec.status == JobStatus.READY


def test_invalid_transition(db):
    db.create_job("job-bad")
    with pytest.raises(InvalidTransitionError):
        db.update_status("job-bad", JobStatus.COMPLETED)
