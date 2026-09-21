"""Printer telemetry must converge with job completion (physical probe, not job status)."""

import asyncio

import pytest

from app.job_manager import JobManager
from app.mock_printer import MockPrinter
from app.models import JobStatus
from app.printer_telemetry.monitor import MockPrinterMonitor
from app.printer_telemetry.service import PrinterTelemetryService
from app.printer_telemetry.types import DisplayState


@pytest.mark.asyncio
async def test_publish_physical_state_force_emits_ready():
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monitor = MockPrinterMonitor(display_state="READY")
    svc = PrinterTelemetryService(
        monitor,
        None,
        "agent-1",
        send_callback=capture,
    )
    snap = await svc.publish_physical_state(force=True)
    assert snap.display_state == DisplayState.READY
    assert len(sent) == 1
    assert sent[0]["display_state"] == "READY"
    assert sent[0]["sequence"] == 1


@pytest.mark.asyncio
async def test_publish_physical_state_force_again_increments_sequence():
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monitor = MockPrinterMonitor(display_state="READY")
    svc = PrinterTelemetryService(
        monitor,
        None,
        "agent-1",
        send_callback=capture,
    )
    await svc.publish_physical_state(force=True)
    await svc.publish_physical_state(force=True)
    assert [m["sequence"] for m in sent] == [1, 2]
    assert all(m["display_state"] == "READY" for m in sent)


@pytest.mark.asyncio
async def test_poll_loop_printing_to_ready_emits_both():
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monitor = MockPrinterMonitor(display_state="READY")
    svc = PrinterTelemetryService(
        monitor,
        None,
        "agent-1",
        poll_interval_seconds=0.05,
        heartbeat_seconds=10.0,
        send_callback=capture,
    )
    monitor._display = "PRINTING"
    svc.start()
    await asyncio.sleep(0.12)
    monitor._display = "READY"
    await asyncio.sleep(0.12)
    await svc.stop()
    displays = [m["display_state"] for m in sent]
    assert "PRINTING" in displays
    assert "READY" in displays


@pytest.mark.asyncio
async def test_flush_on_reconnect_uses_physical_publish():
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monitor = MockPrinterMonitor(display_state="READY")
    svc = PrinterTelemetryService(
        monitor,
        None,
        "agent-1",
        send_callback=capture,
    )
    await svc.flush_on_reconnect()
    assert len(sent) == 1
    assert sent[0]["display_state"] == "READY"


@pytest.mark.asyncio
async def test_before_job_completed_called_before_complete(tmp_path, tmp_job_dirs):
    from app.database import init_db
    from app.downloader import Downloader
    from app.mock_printer import _MockJob

    order: list[str] = []

    async def before_complete() -> None:
        order.append("telemetry")

    db = init_db(tmp_path / "agent.db")
    printer = MockPrinter(delay_seconds=0.01)
    file_path = tmp_job_dirs["processing"] / "doc.pdf"
    file_path.write_bytes(b"%PDF")
    printer._jobs["c1"] = _MockJob(
        backend_job_id="job-1",
        file_path=file_path,
        submitted_at=0.0,
        delay_seconds=0.01,
        simulate_failure=False,
    )

    jm = JobManager(
        db=db,
        downloader=Downloader(tmp_job_dirs["incoming"], 1_000_000, 5),
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
        before_job_completed=before_complete,
    )
    from app.models import PrintSettings

    meta = {
        "filename": "doc.pdf",
        "file_url": "http://example.com/x.pdf",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job("job-1", meta)
    db.set_file_path("job-1", str(file_path))
    db.update_status("job-1", JobStatus.DOWNLOADING)
    db.update_status("job-1", JobStatus.READY)
    db.set_cups_job_id("job-1", "c1")
    db.update_status("job-1", JobStatus.SUBMITTED)

    jm.start()
    await jm.recover_unfinished_jobs()
    for _ in range(80):
        rec = db.get_by_backend_id("job-1")
        if rec and rec.status == JobStatus.COMPLETED:
            break
        await asyncio.sleep(0.05)
    assert db.get_by_backend_id("job-1").status == JobStatus.COMPLETED
    assert "telemetry" in order
    await jm.stop()
    db.close()


@pytest.mark.asyncio
async def test_has_active_print_job_only_when_printing_status(tmp_path):
    from app.database import init_db
    from app.downloader import Downloader

    db = init_db(tmp_path / "agent.db")
    jm = JobManager(
        db=db,
        downloader=Downloader(tmp_path / "incoming", 1_000_000, 5),
        printer=MockPrinter(),
        processing_dir=tmp_path / "processing",
        completed_dir=tmp_path / "completed",
        failed_dir=tmp_path / "failed",
    )
    from app.models import PrintSettings

    meta = {"print_settings": PrintSettings().to_dict()}
    db.create_job("j1", meta)
    db.set_cups_job_id("j1", "cups-1")
    db.update_status("j1", JobStatus.DOWNLOADING)
    db.update_status("j1", JobStatus.READY)
    db.update_status("j1", JobStatus.SUBMITTED)
    assert jm.has_active_print_job() is False
    db.update_status("j1", JobStatus.PRINTING)
    assert jm.has_active_print_job() is True
    db.close()
