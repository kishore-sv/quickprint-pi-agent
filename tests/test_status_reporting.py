"""Tests for backend status event reporting."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.mock_printer import MockPrinter
from app.models import AssignedJob, JobStatus, PrintSettings
from app.protocol import OutboundType, status_message_for_job_status
from app.websocket_client import ConnectionState, WebSocketClient
from tests.conftest import make_job_manager


class StatusCapture:
    def __init__(self) -> None:
        self.events: list[tuple[str, JobStatus, dict[str, Any]]] = []

    async def callback(
        self,
        backend_job_id: str,
        status: JobStatus,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.events.append((backend_job_id, status, dict(extra or {})))

    def outbound_types(self) -> list[str]:
        types: list[str] = []
        for job_id, status, extra in self.events:
            msg = status_message_for_job_status(status.value, job_id, **extra)
            types.append(json.loads(msg)["type"])
        return types


def _make_settings(tmp_path: Path, dirs: dict[str, Path]) -> Settings:
    return Settings(
        agent_env="development",
        agent_id="test-agent-id",
        agent_secret="test-secret",
        backend_url="",
        backend_ws_url="ws://127.0.0.1:1",
        job_directory=dirs["root"],
        database_path=tmp_path / "agent.db",
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
        retry_max_attempts=1,
        retry_base_delay_seconds=0.01,
        retry_max_delay_seconds=0.05,
        cups_command_timeout_seconds=30.0,
        job_poll_interval_seconds=0.01,
    )


async def _wait_for_status(
    db, backend_job_id: str, status: JobStatus, timeout: float = 5.0
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        rec = db.get_by_backend_id(backend_job_id)
        if rec and rec.status == status:
            return
        await asyncio.sleep(0.02)
    rec = db.get_by_backend_id(backend_job_id)
    current = rec.status.value if rec else "missing"
    raise TimeoutError(f"Timed out waiting for {status.value}; current={current}")


@pytest.mark.asyncio
async def test_lifecycle_status_events(db, tmp_job_dirs, http_server):
    capture = StatusCapture()
    printer = MockPrinter(delay_seconds=0.08)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    jm.set_state_change_callback(capture.callback)

    job = AssignedJob(
        backend_job_id="lifecycle-job",
        file_url=http_server,
        filename="doc.pdf",
        print_settings=PrintSettings(),
    )
    await jm.handle_assigned(job)
    await _wait_for_status(db, "lifecycle-job", JobStatus.COMPLETED)

    types = capture.outbound_types()
    assert types == [
        OutboundType.JOB_RECEIVED.value,
        OutboundType.JOB_DOWNLOADING.value,
        OutboundType.JOB_READY.value,
        OutboundType.JOB_SUBMITTED.value,
        OutboundType.JOB_PRINTING.value,
        OutboundType.JOB_COMPLETED.value,
    ]
    assert printer.submit_count == 1
    await jm.stop()


@pytest.mark.asyncio
async def test_failed_during_download(db, tmp_job_dirs):
    class _NotFoundHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), _NotFoundHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bad_url = f"http://127.0.0.1:{port}/missing.pdf"

    from app.retry import RetryPolicy

    capture = StatusCapture()
    downloader = Downloader(tmp_job_dirs["incoming"], 1_000_000, 5)
    jm = JobManager(
        db=db,
        downloader=downloader,
        printer=MockPrinter(delay_seconds=0.05),
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        incoming_dir=tmp_job_dirs["incoming"],
        poll_interval_seconds=0.01,
        retry_policy=RetryPolicy(1, 0.01, 0.05),
    )
    jm.start()
    jm.set_state_change_callback(capture.callback)

    job = AssignedJob(
        backend_job_id="download-fail",
        file_url=bad_url,
        filename="doc.pdf",
    )
    await jm.handle_assigned(job)
    await _wait_for_status(db, "download-fail", JobStatus.FAILED)

    types = capture.outbound_types()
    assert OutboundType.JOB_RECEIVED.value in types
    assert OutboundType.JOB_DOWNLOADING.value in types
    assert types[-1] == OutboundType.JOB_FAILED.value
    failed_extra = next(extra for _, status, extra in capture.events if status == JobStatus.FAILED)
    assert "error" in failed_extra
    assert failed_extra["error"]
    server.shutdown()
    await jm.stop()


@pytest.mark.asyncio
async def test_failed_during_printing(db, tmp_job_dirs, http_server):
    capture = StatusCapture()
    printer = MockPrinter(delay_seconds=0.08, simulate_failure=True)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    jm.set_state_change_callback(capture.callback)

    job = AssignedJob(
        backend_job_id="print-fail",
        file_url=http_server,
        filename="doc.pdf",
    )
    await jm.handle_assigned(job)
    await _wait_for_status(db, "print-fail", JobStatus.FAILED)

    types = capture.outbound_types()
    assert OutboundType.JOB_SUBMITTED.value in types
    assert types[-1] == OutboundType.JOB_FAILED.value
    await jm.stop()


@pytest.mark.asyncio
async def test_duplicate_assignment_does_not_print_twice(db, tmp_job_dirs, http_server):
    capture = StatusCapture()
    printer = MockPrinter(delay_seconds=0.08)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    jm.set_state_change_callback(capture.callback)

    job = AssignedJob(
        backend_job_id="dup-job",
        file_url=http_server,
        filename="doc.pdf",
    )
    await jm.handle_assigned(job)
    await _wait_for_status(db, "dup-job", JobStatus.COMPLETED)

    first_submitted_count = capture.outbound_types().count(
        OutboundType.JOB_SUBMITTED.value
    )
    assert first_submitted_count == 1

    await jm.handle_assigned(job)
    await asyncio.sleep(0.1)

    assert printer.submit_count == 1
    assert capture.outbound_types().count(OutboundType.JOB_SUBMITTED.value) == 1
    await jm.stop()


@pytest.mark.asyncio
async def test_reconnect_does_not_resubmit_cups_job(db, tmp_job_dirs):
    from app.mock_printer import _MockJob

    capture = StatusCapture()
    printer = MockPrinter(delay_seconds=0.08)
    file_path = tmp_job_dirs["processing"] / "recover_doc.pdf"
    file_path.write_bytes(b"%PDF")
    printer.submit_count = 1
    printer._jobs["mock-existing"] = _MockJob(
        backend_job_id="recover-job",
        file_path=file_path,
        submitted_at=0.0,
        delay_seconds=0.08,
        simulate_failure=False,
    )

    meta = {
        "filename": "doc.pdf",
        "file_url": "http://example.com/x.pdf",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job("recover-job", meta)
    db.set_file_path("recover-job", str(file_path))
    db.update_status("recover-job", JobStatus.DOWNLOADING)
    db.update_status("recover-job", JobStatus.READY)
    db.set_cups_job_id("recover-job", "mock-existing")

    jm = make_job_manager(db, tmp_job_dirs, printer)
    jm.set_state_change_callback(capture.callback)
    await jm.recover_unfinished_jobs()
    await _wait_for_status(db, "recover-job", JobStatus.COMPLETED)

    assert printer.submit_count == 1
    types = capture.outbound_types()
    assert OutboundType.JOB_SUBMITTED.value in types
    assert types[-1] == OutboundType.JOB_COMPLETED.value
    await jm.stop()


@pytest.mark.asyncio
async def test_mock_printer_completes_with_completed_event(db, tmp_job_dirs, http_server):
    capture = StatusCapture()
    jm = make_job_manager(db, tmp_job_dirs, MockPrinter(delay_seconds=0.08))
    jm.set_state_change_callback(capture.callback)

    await jm.handle_assigned(
        AssignedJob(
            backend_job_id="complete-job",
            file_url=http_server,
            filename="doc.pdf",
        )
    )
    await _wait_for_status(db, "complete-job", JobStatus.COMPLETED)

    assert capture.outbound_types()[-1] == OutboundType.JOB_COMPLETED.value
    await jm.stop()


@pytest.mark.asyncio
async def test_status_events_contain_backend_job_id(db, tmp_job_dirs, http_server):
    capture = StatusCapture()
    jm = make_job_manager(db, tmp_job_dirs, MockPrinter(delay_seconds=0.08))
    jm.set_state_change_callback(capture.callback)

    backend_job_id = "shape-job-001"
    await jm.handle_assigned(
        AssignedJob(
            backend_job_id=backend_job_id,
            file_url=http_server,
            filename="doc.pdf",
        )
    )
    await _wait_for_status(db, backend_job_id, JobStatus.COMPLETED)

    for job_id, _, _ in capture.events:
        assert job_id == backend_job_id
    for job_id, status, extra in capture.events:
        msg = json.loads(status_message_for_job_status(status.value, job_id, **extra))
        assert msg["job_id"] == backend_job_id
    await jm.stop()


@pytest.mark.asyncio
async def test_callback_signature_with_extra_dict(db, tmp_job_dirs):
    capture = StatusCapture()
    jm = make_job_manager(db, tmp_job_dirs)
    jm.set_state_change_callback(capture.callback)

    db.create_job("emit-test", {"filename": "x.pdf"})
    await jm._emit("emit-test", JobStatus.FAILED, extra={"error": "test error"})

    assert len(capture.events) == 1
    _, status, extra = capture.events[0]
    assert status == JobStatus.FAILED
    assert extra["error"] == "test error"
    await jm.stop()


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)


@pytest.mark.asyncio
async def test_ws_disconnect_queues_and_flushes_on_reconnect(tmp_path, tmp_job_dirs):
    settings = _make_settings(tmp_path, tmp_job_dirs)
    db = init_db(tmp_path / "status.db")
    jm = make_job_manager(db, tmp_job_dirs)
    client = WebSocketClient(settings, jm)

    await client.send_status("queued-job", JobStatus.RECEIVED)
    assert "queued-job" in client._pending_statuses

    fake_ws = _FakeWebSocket()
    client._ws = fake_ws
    client._state = ConnectionState.CONNECTED
    await client._flush_pending_statuses()

    assert len(fake_ws.sent) == 1
    data = json.loads(fake_ws.sent[0])
    assert data["type"] == OutboundType.JOB_RECEIVED.value
    assert data["job_id"] == "queued-job"
    assert data["agent_id"] == "test-agent-id"
    assert "timestamp" in data
    assert "queued-job" not in client._pending_statuses

    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_ws_e2e_job_assigned_lifecycle(tmp_path, tmp_job_dirs, http_server):
    settings = _make_settings(tmp_path, tmp_job_dirs)
    db = init_db(tmp_path / "e2e.db")
    printer = MockPrinter(delay_seconds=0.08)
    jm = make_job_manager(db, tmp_job_dirs, printer)
    client = WebSocketClient(settings, jm)

    fake_ws = _FakeWebSocket()
    client._ws = fake_ws
    client._state = ConnectionState.CONNECTED

    assigned = json.dumps(
        {
            "type": "job.assigned",
            "job_id": "ws-e2e-job",
            "file_url": http_server,
            "filename": "doc.pdf",
            "print_settings": {"copies": 1},
        }
    )
    await client._handle_raw(assigned)
    await _wait_for_status(db, "ws-e2e-job", JobStatus.COMPLETED)

    types = [json.loads(msg)["type"] for msg in fake_ws.sent]
    assert types == [
        OutboundType.JOB_RECEIVED.value,
        OutboundType.JOB_DOWNLOADING.value,
        OutboundType.JOB_READY.value,
        OutboundType.JOB_SUBMITTED.value,
        OutboundType.JOB_PRINTING.value,
        OutboundType.JOB_COMPLETED.value,
    ]
    submitted = next(msg for msg in fake_ws.sent if "submitted" in msg)
    assert "cups_job_id" in json.loads(submitted)
    assert types[-1] == OutboundType.JOB_COMPLETED.value

    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_emit_includes_cups_job_id_from_db(db, tmp_job_dirs):
    capture = StatusCapture()
    jm = make_job_manager(db, tmp_job_dirs)
    jm.set_state_change_callback(capture.callback)

    db.create_job("cups-emit", {"filename": "x.pdf"})
    db.set_cups_job_id("cups-emit", "mock-printer-99")
    db.update_status("cups-emit", JobStatus.DOWNLOADING)
    db.update_status("cups-emit", JobStatus.READY)
    db.update_status("cups-emit", JobStatus.SUBMITTED)

    await jm._emit("cups-emit", JobStatus.PRINTING)

    assert capture.events[-1][2]["cups_job_id"] == "mock-printer-99"
    await jm.stop()
