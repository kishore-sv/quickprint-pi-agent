"""Optional Linux/CUPS integration tests — requires real local CUPS queue."""

import asyncio
import os
import platform
import shutil
from pathlib import Path

import pytest

from app.cups import CupsPrinter
from app.models import PrintSettings
from app.printer import PrinterJobState

pytestmark = pytest.mark.skipif(
    os.environ.get("CUPS_INTEGRATION") != "1"
    or platform.system() != "Linux"
    or shutil.which("lpstat") is None,
    reason="Set CUPS_INTEGRATION=1 on Linux with CUPS configured",
)


@pytest.mark.asyncio
async def test_real_cups_submit_and_complete(tmp_path: Path):
    queue = os.environ.get("CUPS_PRINTER_NAME", "quickprint-test")
    server = os.environ.get("CUPS_SERVER") or None
    printer = CupsPrinter(queue, cups_server=server)

    info = await printer.get_printer_info()
    assert info.get("available"), f"Queue {queue} not available: {info}"

    pdf = tmp_path / "integration.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")

    result = await printer.submit(pdf, "integration-job-001", PrintSettings())
    assert result.printer_job_id

    for _ in range(120):
        status = await printer.get_status(result.printer_job_id)
        if status.state == PrinterJobState.COMPLETED:
            return
        if status.state == PrinterJobState.FAILED:
            pytest.fail(f"CUPS job failed: {status.message}")
        await asyncio.sleep(0.25)

    pytest.fail("Timed out waiting for CUPS job completion")
