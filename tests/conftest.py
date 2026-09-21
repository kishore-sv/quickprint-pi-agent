"""Shared pytest fixtures."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.mock_printer import MockPrinter

TELEMETRY_SETTINGS_KWARGS = {
    "printer_telemetry_enabled": False,
    "printer_telemetry_interval_seconds": 3.0,
    "printer_telemetry_heartbeat_seconds": 10.0,
    "printer_hplip_fallback_enabled": True,
}


class _FileHandler(BaseHTTPRequestHandler):
    file_bytes: bytes = b"%PDF-1.4 test"

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(self.file_bytes)))
        self.end_headers()
        self.wfile.write(self.file_bytes)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def tmp_job_dirs(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "jobs"
    incoming = root / "incoming"
    processing = root / "processing"
    completed = root / "completed"
    failed = root / "failed"
    for d in (incoming, processing, completed, failed):
        d.mkdir(parents=True)
    return {
        "root": root,
        "incoming": incoming,
        "processing": processing,
        "completed": completed,
        "failed": failed,
    }


@pytest.fixture
def http_server() -> str:
    server = HTTPServer(("127.0.0.1", 0), _FileHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/file.pdf"
    server.shutdown()


@pytest.fixture
def db(tmp_path: Path):
    database = init_db(tmp_path / "agent.db")
    yield database
    database.close()


def make_job_manager(
    db,
    dirs: dict[str, Path],
    printer: MockPrinter | None = None,
) -> JobManager:
    printer = printer or MockPrinter(delay_seconds=0.05, simulate_failure=False)
    downloader = Downloader(dirs["incoming"], max_bytes=1_000_000, timeout_seconds=5)
    jm = JobManager(
        db=db,
        downloader=downloader,
        printer=printer,
        processing_dir=dirs["processing"],
        completed_dir=dirs["completed"],
        failed_dir=dirs["failed"],
        incoming_dir=dirs["incoming"],
        poll_interval_seconds=0.01,
        physical_completion_stable_seconds=0,
    )
    jm.start()
    return jm
