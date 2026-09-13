import asyncio
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.database import init_db
from app.downloader import Downloader
from app.job_manager import JobManager
from app.mock_printer import MockPrinter
from app.models import AssignedJob, JobStatus, PrintSettings

_TEST_PDF = b"%PDF-1.4 quickprint manual test"


class _TestFileHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(_TEST_PDF)))
        self.end_headers()
        self.wfile.write(_TEST_PDF)

    def log_message(self, format: str, *args: object) -> None:
        return


def _start_http_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 8765), _TestFileHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def _wait_for_status(db, backend_job_id: str, status: JobStatus, timeout: float) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        record = db.get_by_backend_id(backend_job_id)
        if record is not None and record.status == status:
            return
        await asyncio.sleep(0.05)
    record = db.get_by_backend_id(backend_job_id)
    current = record.status.value if record else "missing"
    raise TimeoutError(
        f"Timed out waiting for {status.value}; current status={current}"
    )


async def main():
    http_server = _start_http_server()

    with TemporaryDirectory(prefix="quickprint-test-") as tmp:
        root = Path(tmp)

        incoming = root / "incoming"
        processing = root / "processing"
        completed = root / "completed"
        failed = root / "failed"

        for directory in (incoming, processing, completed, failed):
            directory.mkdir(parents=True)

        db = init_db(root / "agent.db")

        printer = MockPrinter(
            delay_seconds=0.2,
            simulate_failure=False,
        )

        downloader = Downloader(
            incoming_dir=incoming,
            max_bytes=1_000_000,
            timeout_seconds=5,
        )

        manager = JobManager(
            db=db,
            downloader=downloader,
            printer=printer,
            processing_dir=processing,
            completed_dir=completed,
            failed_dir=failed,
            poll_interval_seconds=0.05,
        )

        manager.start()

        job = AssignedJob(
            backend_job_id="manual-test-job-001",
            file_url="http://127.0.0.1:8765/test-print.pdf",
            filename="test-print.pdf",
            print_settings=PrintSettings(
                copies=1,
                color_mode="bw",
                paper_size="A4",
                duplex=False,
                pages_per_sheet=1,
                order="normal",
                orientation="auto",
                fit_to_page=True,
            ),
        )

        print("\n=== First submission ===")
        print("Job ID:", job.backend_job_id)
        await manager.handle_assigned(job)
        await _wait_for_status(db, job.backend_job_id, JobStatus.COMPLETED, timeout=30.0)

        print("\n=== Second submission (same backend_job_id) ===")
        await manager.handle_assigned(job)
        await asyncio.sleep(0.5)

        record = db.get_by_backend_id(job.backend_job_id)
        if record is None:
            raise AssertionError("Job record was not found in SQLite")

        print("\n=== Duplicate protection check ===")
        print("Final status:", record.status.value)
        print("Printer job ID:", record.cups_job_id)
        print("Mock printer submit_count:", printer.submit_count)

        assert record.status == JobStatus.COMPLETED, (
            f"Expected COMPLETED, got {record.status.value}"
        )
        assert printer.submit_count == 1, (
            f"Expected exactly one print submit, got {printer.submit_count}"
        )

        print("\nDUPLICATE PROTECTION TEST PASSED: job was printed exactly once.")

        await manager.stop()
        db.close()

    http_server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
