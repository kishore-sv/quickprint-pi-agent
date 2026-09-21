"""CUPS lpstat -p idle gate for physical job completion."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.cups import CupsPrinter
from app.cups_command import CommandResult
from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.models import InvalidTransitionError, JobStatus
from app.printer import PrinterJobState, PrinterJobStatus
from tests.fake_cups_runner import FakeCupsRunner


def _runner_idle(printer_name: str) -> FakeCupsRunner:
    runner = FakeCupsRunner()
    runner.responses[("lpstat", "-p", printer_name)] = CommandResult(
        0, f"printer {printer_name} is idle", ""
    )
    runner.responses[("lpstat", "-r")] = CommandResult(0, "scheduler is running", "")
    return runner


def _runner_printing(printer_name: str) -> FakeCupsRunner:
    runner = FakeCupsRunner()
    runner.responses[("lpstat", "-p", printer_name)] = CommandResult(
        0, f"printer {printer_name} now printing", ""
    )
    runner.responses[("lpstat", "-r")] = CommandResult(0, "scheduler is running", "")
    return runner


def _completed_job_runner(
    printer_name: str, cups_job_id: str, *, printer_runner: FakeCupsRunner
) -> FakeCupsRunner:
    printer_runner.responses[("lpstat", "-o", printer_name)] = CommandResult(0, "", "")
    printer_runner.responses[("lpstat", "-W", "completed", "-o", printer_name)] = (
        CommandResult(0, f"{cups_job_id} user completed", "")
    )
    return printer_runner


def _jm(tmp_path: Path, printer: CupsPrinter, **kwargs) -> JobManager:
    incoming = tmp_path / "incoming"
    processing = tmp_path / "processing"
    completed = tmp_path / "completed"
    failed = tmp_path / "failed"
    for d in (incoming, processing, completed, failed):
        d.mkdir(parents=True, exist_ok=True)
    db = init_db(tmp_path / "agent.db")
    stable = kwargs.pop("physical_completion_stable_seconds", 0)
    return JobManager(
        db=db,
        downloader=Downloader(incoming, 1_000_000, 5),
        printer=printer,
        processing_dir=processing,
        completed_dir=completed,
        failed_dir=failed,
        poll_interval_seconds=0.01,
        physical_completion_stable_seconds=stable,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_get_queue_printer_flags_idle(tmp_path):
    name = "quickprint-printer"
    runner = _runner_idle(name)
    printer = CupsPrinter(name, runner=runner)
    flags = await printer.get_queue_printer_flags()
    assert flags["ok"] is True
    assert flags["idle"] is True
    assert flags["printing"] is False


@pytest.mark.asyncio
async def test_get_queue_printer_flags_failure_not_idle(tmp_path):
    name = "quickprint-printer"
    runner = FakeCupsRunner()
    runner.responses[("lpstat", "-p", name)] = CommandResult(1, "", "error")
    printer = CupsPrinter(name, runner=runner)
    flags = await printer.get_queue_printer_flags()
    assert flags["ok"] is False
    assert flags["idle"] is False


@pytest.mark.asyncio
async def test_a_completed_job_and_printer_idle(tmp_path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_idle(name))
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer)

    ready, evidence = await jm._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready is True
    assert "cups_terminal" in evidence


@pytest.mark.asyncio
async def test_b_completed_job_printer_still_printing(tmp_path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_printing(name))
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer)

    ready, reason = await jm._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready is False
    assert reason == "cups_printer_still_printing"


@pytest.mark.asyncio
async def test_c_completed_job_printer_state_unknown(tmp_path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=FakeCupsRunner())
    runner.responses[("lpstat", "-p", name)] = CommandResult(1, "", "fail")
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer)

    ready, reason = await jm._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready is False
    assert reason == "cups_printer_state_unknown"


@pytest.mark.asyncio
async def test_d_job_still_active(tmp_path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _runner_idle(name)
    runner.responses[("lpstat", "-o", name)] = CommandResult(
        0, f"{job_id} user processing", ""
    )
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer)

    ready, reason = await jm._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready is False
    assert reason == "cups_job_still_active"


@pytest.mark.asyncio
async def test_e_lpstat_timeout_blocks_completion(tmp_path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_idle(name))
    runner.timeout_on.add(("lpstat", "-p", name))
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer)

    ready, reason = await jm._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready is False
    assert reason == "cups_printer_state_unknown"


@pytest.mark.asyncio
async def test_f_stale_telemetry_checker_blocked_cups_idle_still_completes(tmp_path):
    """Telemetry-style checker would block; CUPS idle gate is authoritative when checker passes."""
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_idle(name))
    printer = CupsPrinter(name, runner=runner)

    async def stale_telemetry_block(_cups_id: str) -> tuple[bool, str]:
        return False, "printer_operational_printing"

    jm = _jm(
        tmp_path,
        printer,
        physical_completion_checker=stale_telemetry_block,
    )

    ready, reason = await jm._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready is False
    assert reason == "printer_operational_printing"

    jm2 = _jm(tmp_path / "b", printer, physical_completion_checker=None)
    ready2, _ = await jm2._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready2 is True


@pytest.mark.asyncio
async def test_g_cups_printing_blocks_even_if_checker_passes(tmp_path):
    name = "quickprint-printer"
    job_id = "quickprint-printer-77"
    runner = _completed_job_runner(name, job_id, printer_runner=_runner_printing(name))
    printer = CupsPrinter(name, runner=runner)

    async def always_ready(_cups_id: str) -> tuple[bool, str]:
        return True, "printer_quiescent"

    jm = _jm(tmp_path, printer, physical_completion_checker=always_ready)
    ready, reason = await jm._evaluate_physical_completion(
        "backend-1",
        job_id,
        PrinterJobStatus(job_id, PrinterJobState.COMPLETED),
    )
    assert ready is False
    assert reason == "cups_printer_still_printing"


@pytest.mark.asyncio
async def test_h_duplicate_completed_transition_rejected(tmp_path):
    name = "quickprint-printer"
    db_path = tmp_path / "agent.db"
    runner = _runner_idle(name)
    printer = CupsPrinter(name, runner=runner)
    jm = _jm(tmp_path, printer)
    db = jm._db
    from app.models import PrintSettings

    db.create_job("dup-job", {"print_settings": PrintSettings().to_dict()})
    db.update_status("dup-job", JobStatus.DOWNLOADING)
    db.update_status("dup-job", JobStatus.READY)
    db.update_status("dup-job", JobStatus.SUBMITTED)
    db.update_status("dup-job", JobStatus.PRINTING)
    db.update_status("dup-job", JobStatus.COMPLETED)

    with pytest.raises(InvalidTransitionError):
        db.update_status("dup-job", JobStatus.PRINTING)
