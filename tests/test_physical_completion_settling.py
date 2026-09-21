"""Physical completion settling after CUPS job COMPLETED."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.cups import CupsPrinter
from app.cups_command import CommandResult
from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.models import JobStatus
from app.printer import PrinterJobState, PrinterJobStatus
from tests.fake_cups_runner import FakeCupsRunner
from tests.test_cups_completion_gate import (
    _completed_job_runner,
    _jm,
    _runner_idle,
    _runner_printing,
)


@pytest.mark.asyncio
async def test_completes_after_stable_period(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_idle(name))
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer, physical_completion_stable_seconds=2)

    clock = {"t": 1000.0}
    monkeypatch.setattr("app.job_manager.time.monotonic", lambda: clock["t"])

    status = PrinterJobStatus(job_id, PrinterJobState.COMPLETED)
    ready, reason = await jm._evaluate_physical_completion("job-a", job_id, status)
    assert ready is False
    assert reason == "physical_completion_settling"

    clock["t"] = 1001.0
    ready, reason = await jm._evaluate_physical_completion("job-a", job_id, status)
    assert ready is False
    assert reason == "physical_completion_settling"

    clock["t"] = 1002.0
    ready, evidence = await jm._evaluate_physical_completion("job-a", job_id, status)
    assert ready is True
    assert "stable_2" in evidence


@pytest.mark.asyncio
async def test_printing_during_settling_resets_timer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    idle_runner = _runner_idle(name)
    runner = _completed_job_runner(name, job_id, printer_runner=idle_runner)
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer, physical_completion_stable_seconds=2)

    clock = {"t": 2000.0}
    monkeypatch.setattr("app.job_manager.time.monotonic", lambda: clock["t"])

    status = PrinterJobStatus(job_id, PrinterJobState.COMPLETED)
    await jm._evaluate_physical_completion("job-b", job_id, status)
    clock["t"] = 2001.5

    idle_runner.responses[("lpstat", "-p", name)] = CommandResult(
        0, f"printer {name} now printing", ""
    )
    ready, reason = await jm._evaluate_physical_completion("job-b", job_id, status)
    assert ready is False
    assert reason == "cups_printer_still_printing"

    idle_runner.responses[("lpstat", "-p", name)] = CommandResult(
        0, f"printer {name} is idle", ""
    )
    clock["t"] = 2002.0
    ready, reason = await jm._evaluate_physical_completion("job-b", job_id, status)
    assert ready is False
    assert reason == "physical_completion_settling"

    clock["t"] = 2004.0
    ready, _ = await jm._evaluate_physical_completion("job-b", job_id, status)
    assert ready is True


@pytest.mark.asyncio
async def test_printer_still_printing_never_completes(tmp_path: Path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_printing(name))
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer, physical_completion_stable_seconds=2)

    status = PrinterJobStatus(job_id, PrinterJobState.COMPLETED)
    for _ in range(5):
        ready, reason = await jm._evaluate_physical_completion(
            "job-c", job_id, status
        )
        assert ready is False
        assert reason == "cups_printer_still_printing"


@pytest.mark.asyncio
async def test_duplicate_completed_emit_once(tmp_path: Path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_idle(name))
    printer = CupsPrinter(name, runner=runner)
    emissions: list[JobStatus] = []

    async def on_change(job_id: str, status: JobStatus, _extra: dict) -> None:
        emissions.append(status)

    incoming = tmp_path / "incoming"
    processing = tmp_path / "processing"
    completed = tmp_path / "completed"
    failed = tmp_path / "failed"
    for d in (incoming, processing, completed, failed):
        d.mkdir(parents=True, exist_ok=True)
    db = init_db(tmp_path / "agent.db")
    jm = JobManager(
        db=db,
        downloader=Downloader(incoming, 1_000_000, 5),
        printer=printer,
        processing_dir=processing,
        completed_dir=completed,
        failed_dir=failed,
        poll_interval_seconds=0.01,
        physical_completion_stable_seconds=0,
        on_state_change=on_change,
    )

    db.create_job("dup-emit", {"print_settings": {}})
    for st in (
        JobStatus.DOWNLOADING,
        JobStatus.READY,
        JobStatus.SUBMITTED,
        JobStatus.PRINTING,
    ):
        db.update_status("dup-emit", st)

    file_path = processing / "doc.pdf"
    file_path.write_bytes(b"x")
    db.set_file_path("dup-emit", str(file_path))
    db.set_cups_job_id("dup-emit", job_id)

    status = PrinterJobStatus(job_id, PrinterJobState.COMPLETED)
    stopped = await jm._process_printer_poll_status(
        "dup-emit", job_id, status, file_path
    )
    assert stopped is True
    stopped_again = await jm._process_printer_poll_status(
        "dup-emit", job_id, status, file_path
    )
    assert stopped_again is True
    assert emissions.count(JobStatus.COMPLETED) == 1


@pytest.mark.asyncio
async def test_reconnect_clears_in_memory_settling_without_false_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """New JobManager after restart must not inherit settling timer from memory."""
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_idle(name))
    printer = CupsPrinter(name, runner=runner)
    jm1 = _jm(tmp_path, printer, physical_completion_stable_seconds=5)

    clock = {"t": 3000.0}
    monkeypatch.setattr("app.job_manager.time.monotonic", lambda: clock["t"])

    status = PrinterJobStatus(job_id, PrinterJobState.COMPLETED)
    ready, _ = await jm1._evaluate_physical_completion("job-r", job_id, status)
    assert ready is False

    jm2 = _jm(tmp_path / "restart", printer, physical_completion_stable_seconds=5)
    clock["t"] = 3004.0
    ready, reason = await jm2._evaluate_physical_completion("job-r", job_id, status)
    assert ready is False
    assert reason == "physical_completion_settling"


@pytest.mark.asyncio
async def test_terminal_state_protection_unchanged(tmp_path: Path):
    from app.models import InvalidTransitionError

    name = "quickprint-printer"
    jm = _jm(tmp_path, CupsPrinter(name, runner=_runner_idle(name)))
    db = jm._db
    db.create_job("term", {"print_settings": {}})
    for st in (
        JobStatus.DOWNLOADING,
        JobStatus.READY,
        JobStatus.SUBMITTED,
        JobStatus.PRINTING,
        JobStatus.COMPLETED,
    ):
        db.update_status("term", st)
    with pytest.raises(InvalidTransitionError):
        db.update_status("term", JobStatus.PRINTING)
