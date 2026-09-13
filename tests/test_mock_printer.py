"""MockPrinter tests."""

import asyncio
from pathlib import Path

import pytest

from app.mock_printer import MockPrinter
from app.models import PrintSettings
from app.printer import PrinterJobState


@pytest.mark.asyncio
async def test_mock_printer_success(tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"pdf")
    printer = MockPrinter(delay_seconds=0.05, simulate_failure=False)
    result = await printer.submit(f, "job-1", PrintSettings())
    status = await printer.get_status(result.printer_job_id)
    assert status.state in (
        PrinterJobState.PENDING,
        PrinterJobState.PRINTING,
        PrinterJobState.COMPLETED,
    )
    for _ in range(50):
        status = await printer.get_status(result.printer_job_id)
        if status.state == PrinterJobState.COMPLETED:
            break
        await asyncio.sleep(0.02)
    assert status.state == PrinterJobState.COMPLETED


@pytest.mark.asyncio
async def test_mock_printer_failure(tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"pdf")
    printer = MockPrinter(delay_seconds=0.05, simulate_failure=True)
    result = await printer.submit(f, "job-2", PrintSettings())
    await asyncio.sleep(0.1)
    status = await printer.get_status(result.printer_job_id)
    assert status.state == PrinterJobState.FAILED
