"""CUPS submission timeout and exact title matching safety tests."""

import asyncio
from pathlib import Path

import pytest

from app.cups import CupsPrinter, _parse_job_state
from app.cups_command import CommandResult, CupsCommandTimeoutError
from app.cups_job_identity import cups_job_title, lpstat_text_contains_exact_title
from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.models import AssignedJob, JobStatus, PrintSettings
from app.printer import (
    PrinterJobState,
    PrinterSubmissionUncertainError,
)
from tests.fake_cups_runner import FakeCupsRunner


def _base_runner() -> FakeCupsRunner:
    runner = FakeCupsRunner()
    runner.responses[("lpstat", "-p", "PiPrinter")] = CommandResult(
        0, "printer PiPrinter is idle", ""
    )
    runner.responses[("lpstat", "-r")] = CommandResult(0, "scheduler is running", "")
    return runner


@pytest.mark.asyncio
async def test_lp_timeout_adopts_existing_job(tmp_path: Path):
    backend_job_id = "timeout-found-1"
    title = cups_job_title(backend_job_id)
    runner = _base_runner()
    printer = CupsPrinter("PiPrinter", runner=runner)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            raise CupsCommandTimeoutError("lp timed out")
        key = tuple(args)
        if key in runner.responses:
            return runner.responses[key]
        if args == ["lpstat", "-o"]:
            return CommandResult(0, f"PiPrinter-77 user 1024\n", "")
        if args == ["lpstat", "-l", "-o", "PiPrinter-77"]:
            return CommandResult(0, f"Title: {title}\n", "")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(1, "", "")
        return CommandResult(1, "", "missing")

    runner.run = flex  # type: ignore[method-assign]

    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    result = await printer.submit(f, backend_job_id, PrintSettings())
    assert result.printer_job_id == "PiPrinter-77"
    assert runner.lp_call_count == 1


@pytest.mark.asyncio
async def test_lp_timeout_not_found_raises_uncertain(tmp_path: Path):
    runner = _base_runner()
    printer = CupsPrinter("PiPrinter", runner=runner)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            raise CupsCommandTimeoutError("lp timed out")
        if args == ["lpstat", "-o"]:
            return CommandResult(0, "", "")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(0, "", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", ""))

    runner.run = flex  # type: ignore[method-assign]
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    with pytest.raises(PrinterSubmissionUncertainError):
        await printer.submit(f, "missing-job", PrintSettings())
    assert runner.lp_call_count == 1


@pytest.mark.asyncio
async def test_lp_timeout_ambiguous_raises_uncertain(tmp_path: Path):
    backend_job_id = "timeout-amb"
    title = cups_job_title(backend_job_id)
    runner = _base_runner()
    printer = CupsPrinter("PiPrinter", runner=runner)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            raise CupsCommandTimeoutError("lp timed out")
        if args == ["lpstat", "-o"]:
            return CommandResult(
                0, "PiPrinter-1 user\nPiPrinter-2 user\n", ""
            )
        if args == ["lpstat", "-l", "-o", "PiPrinter-1"]:
            return CommandResult(0, f"Title: {title}\n", "")
        if args == ["lpstat", "-l", "-o", "PiPrinter-2"]:
            return CommandResult(0, f"Title: {title}\n", "")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(1, "", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", ""))

    runner.run = flex  # type: ignore[method-assign]
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    with pytest.raises(PrinterSubmissionUncertainError):
        await printer.submit(f, backend_job_id, PrintSettings())
    assert runner.lp_call_count == 1


@pytest.mark.asyncio
async def test_lp_timeout_lookup_failed_raises_uncertain(tmp_path: Path):
    runner = _base_runner()
    printer = CupsPrinter("PiPrinter", runner=runner)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            raise CupsCommandTimeoutError("lp timed out")
        if args[:2] == ["lpstat", "-o"] or args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(1, "", "lpstat failed")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", ""))

    runner.run = flex  # type: ignore[method-assign]
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    with pytest.raises(PrinterSubmissionUncertainError):
        await printer.submit(f, "lookup-fail", PrintSettings())
    assert runner.lp_call_count == 1


@pytest.mark.asyncio
async def test_exact_title_no_prefix_collision():
    assert not lpstat_text_contains_exact_title(
        "Title: QuickPrint:abc123-other\n", cups_job_title("abc123")
    )
    assert lpstat_text_contains_exact_title(
        "Title: QuickPrint:abc123\n", cups_job_title("abc123")
    )

    runner = _base_runner()
    printer = CupsPrinter("PiPrinter", runner=runner)

    async def flex(args, timeout):
        if args == ["lpstat", "-o"]:
            return CommandResult(
                0,
                "PiPrinter-1 user\nPiPrinter-2 user\n",
                "",
            )
        if args == ["lpstat", "-l", "-o", "PiPrinter-1"]:
            return CommandResult(0, "Title: QuickPrint:abc123-other\n", "")
        if args == ["lpstat", "-l", "-o", "PiPrinter-2"]:
            return CommandResult(0, "Title: QuickPrint:abc123\n", "")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(1, "", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", ""))

    runner.run = flex  # type: ignore[method-assign]
    lookup = await printer.find_existing_job("abc123")
    assert lookup.status.value == "found"
    assert lookup.printer_job_id == "PiPrinter-2"


def test_unrecognized_lpstat_output_is_unknown():
    assert _parse_job_state("foo bar baz", "") == PrinterJobState.UNKNOWN


@pytest.mark.asyncio
async def test_timeout_not_found_fails_job_in_manager(tmp_job_dirs, tmp_path):
    runner = _base_runner()
    printer = CupsPrinter("PiPrinter", runner=runner)

    async def flex(args, timeout):
        if args and args[0] == "lp":
            runner.lp_call_count += 1
            raise CupsCommandTimeoutError("lp timed out")
        if args == ["lpstat", "-o"]:
            return CommandResult(0, "", "")
        if args[:3] == ["lpstat", "-W", "completed"]:
            return CommandResult(0, "", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", ""))

    runner.run = flex  # type: ignore[method-assign]

    db = init_db(tmp_path / "agent.db")
    file_path = tmp_job_dirs["processing"] / "j_doc.pdf"
    file_path.write_bytes(b"%PDF")
    meta = {
        "filename": "doc.pdf",
        "file_url": "http://example.com/x",
        "print_settings": PrintSettings().to_dict(),
    }
    db.create_job("j", meta)
    db.set_file_path("j", str(file_path))
    db.update_status("j", JobStatus.DOWNLOADING)
    db.update_status("j", JobStatus.READY)

    jm = JobManager(
        db=db,
        downloader=Downloader(tmp_job_dirs["incoming"], 1_000_000, 5),
        printer=printer,
        processing_dir=tmp_job_dirs["processing"],
        completed_dir=tmp_job_dirs["completed"],
        failed_dir=tmp_job_dirs["failed"],
        poll_interval_seconds=0.01,
    )
    jm.start()
    job = AssignedJob(
        backend_job_id="j",
        file_url="http://example.com/x",
        filename="doc.pdf",
    )
    await jm._resume_ready_job(job, db.get_by_backend_id("j"), file_path)
    await asyncio.sleep(0.05)
    rec = db.get_by_backend_id("j")
    assert rec is not None
    assert rec.status == JobStatus.FAILED
    assert runner.lp_call_count == 1
    await jm.stop()
    db.close()
