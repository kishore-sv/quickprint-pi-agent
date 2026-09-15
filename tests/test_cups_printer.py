import pytest
from pathlib import Path

from app.cups import CupsPrinter
from app.cups_command import CommandResult, CupsCommandTimeoutError
from app.models import PrintSettings
from app.printer import (
    PrinterJobState,
    PrinterSubmissionError,
    PrinterUnavailableError,
)
from tests.fake_cups_runner import FakeCupsRunner


def _printer_available_runner(name: str = "TestPrinter") -> FakeCupsRunner:
    r = FakeCupsRunner()
    r.responses[("lpstat", "-p", name)] = CommandResult(
        0, f"printer {name} is idle", ""
    )
    r.responses[("lpstat", "-r")] = CommandResult(0, "scheduler is running", "")
    return r


@pytest.mark.asyncio
async def test_lp_submission_success(tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    runner = _printer_available_runner()
    runner.responses[("lp", "-d", "TestPrinter", "-n", "1", "-o", "media=A4", "-o", "print-color-mode=monochrome", "-o", "sides=one-sided", "-o", "fit-to-page=true", "-o", "outputorder=normal", str(f))] = (
        CommandResult(0, "request id is TestPrinter-42", "")
    )
    # build_lp_argv may have many -o flags; use prefix match via custom runner
    printer = CupsPrinter("TestPrinter", runner=runner)

    async def flexible_run(args, timeout_seconds):
        runner.calls.append(args)
        if args[0] == "lp":
            runner.lp_call_count += 1
            return CommandResult(0, "request id is TestPrinter-42", "")
        key = tuple(args)
        return runner.responses.get(key, CommandResult(1, "", "missing"))

    runner.run = flexible_run  # type: ignore[method-assign]
    result = await printer.submit(f, "job-1", PrintSettings())
    assert result.printer_job_id == "TestPrinter-42"
    assert runner.lp_call_count == 1


@pytest.mark.asyncio
async def test_printer_unavailable(tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    runner = FakeCupsRunner()
    printer = CupsPrinter("Missing", runner=runner)
    with pytest.raises(PrinterUnavailableError):
        await printer.submit(f, "j", PrintSettings())


@pytest.mark.asyncio
async def test_lp_failure(tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    runner = _printer_available_runner()

    async def flex(args, timeout):
        if args[0] == "lp":
            return CommandResult(1, "", "printer error")
        return await FakeCupsRunner.run(runner, args, timeout)

    runner.run = flex  # type: ignore[method-assign]
    printer = CupsPrinter("TestPrinter", runner=runner)
    with pytest.raises(PrinterSubmissionError):
        await printer.submit(f, "j", PrintSettings())


@pytest.mark.asyncio
async def test_job_status_pending_processing_completed():
    runner = FakeCupsRunner()
    printer = CupsPrinter("P", runner=runner)
    runner.responses[("lpstat", "-o", "P-1")] = CommandResult(
        0, "P-1 user  pending", ""
    )
    st = await printer.get_status("P-1")
    assert st.state == PrinterJobState.PENDING

    runner.responses[("lpstat", "-o", "P-1")] = CommandResult(
        0, "P-1 user  processing", ""
    )
    st = await printer.get_status("P-1")
    assert st.state == PrinterJobState.PRINTING

    runner.responses[("lpstat", "-o", "P-1")] = CommandResult(1, "", "gone")
    runner.responses[("lpstat", "-W", "completed", "-o", "P-1")] = CommandResult(
        0, "P-1 user  completed", ""
    )
    st = await printer.get_status("P-1")
    assert st.state == PrinterJobState.COMPLETED


@pytest.mark.asyncio
async def test_unknown_job():
    runner = FakeCupsRunner()
    printer = CupsPrinter("P", runner=runner)
    st = await printer.get_status("missing-99")
    assert st.state == PrinterJobState.UNKNOWN


@pytest.mark.asyncio
async def test_cancel():
    runner = FakeCupsRunner()
    runner.responses[("cancel", "P-9")] = CommandResult(0, "", "")
    printer = CupsPrinter("P", runner=runner)
    await printer.cancel("P-9")


@pytest.mark.asyncio
async def test_printer_info_discovery():
    runner = _printer_available_runner("OfficeQ")
    runner.responses[("lpstat", "-p", "OfficeQ")] = CommandResult(
        0,
        "printer OfficeQ is idle, accepting jobs since Mon 01 Jan 2024",
        "",
    )
    printer = CupsPrinter("OfficeQ", runner=runner)
    info = await printer.get_printer_info()
    assert info["available"] is True
    assert info["enabled"] is True
    assert info["accepting_jobs"] is True
    assert info["cups_scheduler_running"] is True


@pytest.mark.asyncio
async def test_cups_server_env_passed_to_runner(tmp_path: Path):
    from app.cups_command import AsyncSubprocessCupsRunner

    captured_env: dict[str, str] = {}

    class _CaptureRunner(AsyncSubprocessCupsRunner):
        async def run(self, args, timeout_seconds):
            captured_env.update(self._extra_env)
            return CommandResult(1, "", "missing")

    runner = _CaptureRunner(extra_env={"CUPS_SERVER": "192.168.1.10"})
    printer = CupsPrinter("P", runner=runner, cups_server="192.168.1.10")
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    with pytest.raises(PrinterUnavailableError):
        await printer.submit(f, "j", PrintSettings())
    assert captured_env.get("CUPS_SERVER") == "192.168.1.10"


@pytest.mark.asyncio
async def test_timeout():
    runner = FakeCupsRunner()
    runner.timeout_on.add(("lpstat", "-p", "P"))

    async def run(args, timeout):
        if tuple(args) in runner.timeout_on:
            raise CupsCommandTimeoutError("timeout")
        return CommandResult(0, "", "")

    runner.run = run  # type: ignore[method-assign]
    printer = CupsPrinter("P", runner=runner)
    assert await printer.health_check() is False
