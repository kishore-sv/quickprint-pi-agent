"""Job cancellation tests."""

import asyncio

import pytest

from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.models import AssignedJob, JobStatus, PrintSettings
from app.mock_printer import MockPrinter
from tests.conftest import make_job_manager


@pytest.mark.asyncio
async def test_handle_cancel_during_downloading(db, tmp_job_dirs):
    capture: list[tuple[str, JobStatus]] = []

    async def on_change(job_id, status, extra=None):
        capture.append((job_id, status))

    printer = MockPrinter(delay_seconds=0.2)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    jm.set_state_change_callback(on_change)

    meta = {
        "filename": "doc.pdf",
        "file_url": "http://example.com/x.pdf",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job("cancel-early", meta)
    db.update_status("cancel-early", JobStatus.DOWNLOADING)

    await jm.handle_cancel("cancel-early")

    rec = db.get_by_backend_id("cancel-early")
    assert rec is not None
    assert rec.status == JobStatus.CANCELLED
    assert any(s == JobStatus.CANCELLED for _, s in capture)
    await jm.stop()


@pytest.mark.asyncio
async def test_monitor_printer_cancelled_transition(db, tmp_job_dirs, http_server):
    printer = MockPrinter(delay_seconds=1.0)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    job = AssignedJob(
        backend_job_id="cancel-mid",
        file_url=http_server,
        filename="doc.pdf",
    )
    await jm.enqueue_assigned(job)
    cups_id: str | None = None
    for _ in range(200):
        rec = db.get_by_backend_id("cancel-mid")
        if rec and rec.cups_job_id:
            cups_id = rec.cups_job_id
            mock_job = printer._jobs.get(cups_id)
            if mock_job:
                mock_job.cancelled = True
            break
        await asyncio.sleep(0.01)
    assert cups_id is not None
    for _ in range(200):
        rec = db.get_by_backend_id("cancel-mid")
        if rec and rec.status == JobStatus.FAILED:
            break
        await asyncio.sleep(0.01)
    rec = db.get_by_backend_id("cancel-mid")
    assert rec is not None
    assert rec.status == JobStatus.FAILED
    await jm.stop()


@pytest.mark.asyncio
async def test_websocket_cancel_message(db, tmp_job_dirs):
    from app.config import Settings
    from app.websocket_client import ConnectionState, WebSocketClient
    from pathlib import Path
    import json

    settings = Settings(
        agent_env="development",
        agent_id="a1",
        agent_secret="s1",
        backend_url="",
        backend_ws_url="ws://127.0.0.1:1",
        job_directory=tmp_job_dirs["root"],
        database_path=tmp_job_dirs["root"] / "agent.db",
        printer_mode="mock",
        cups_printer_name="",
        cups_server="",
        log_level="INFO",
        health_refresh_interval_seconds=60.0,
        max_download_bytes=1_000_000,
        mock_print_delay_seconds=0.1,
        mock_print_failure=False,
        download_timeout_seconds=5,
        heartbeat_interval_seconds=30,
        ws_reconnect_max_delay_seconds=4,
        retry_max_attempts=3,
        retry_base_delay_seconds=1.0,
        retry_max_delay_seconds=30.0,
        cups_command_timeout_seconds=30.0,
        job_poll_interval_seconds=0.01,
    )
    jm = make_job_manager(db, tmp_job_dirs)
    client = WebSocketClient(settings, jm)
    client._state = ConnectionState.CONNECTED

    meta = {
        "filename": "doc.pdf",
        "file_url": "http://example.com/x.pdf",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job("ws-cancel", meta)

    await client._handle_raw(
        json.dumps({"type": "job.cancel", "job_id": "ws-cancel"})
    )
    rec = db.get_by_backend_id("ws-cancel")
    assert rec is not None
    assert rec.status == JobStatus.CANCELLED
    await jm.stop()
