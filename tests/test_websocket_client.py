import json

import pytest

from app.protocol import ProtocolError, parse_message


def test_malformed_ws_message():
    with pytest.raises(ProtocolError):
        parse_message("{not json")


def test_valid_ping():
    msg = parse_message(json.dumps({"type": "ping"}))
    assert msg.type.value == "ping"


@pytest.mark.asyncio
async def test_reconnect_backoff_increases(tmp_path):
    from pathlib import Path

    from app.config import Settings
    from app.database import init_db
    from app.downloader import Downloader
    from app.job_manager import JobManager
    from app.mock_printer import MockPrinter
    from app.websocket_client import WebSocketClient

    db_path = tmp_path / "agent.db"
    db = init_db(db_path)
    dirs = tmp_path / "jobs"
    for sub in ("in", "p", "c", "f"):
        (dirs / sub).mkdir(parents=True)
    printer = MockPrinter()
    jm = JobManager(
        db=db,
        downloader=Downloader(dirs / "in", 1_000, 5),
        printer=printer,
        processing_dir=dirs / "p",
        completed_dir=dirs / "c",
        failed_dir=dirs / "f",
    )
    settings = Settings(
        agent_env="development",
        agent_id="",
        agent_secret="",
        backend_url="",
        backend_ws_url="ws://127.0.0.1:1",
        job_directory=dirs,
        database_path=db_path,
        printer_mode="mock",
        cups_printer_name="",
        log_level="INFO",
        max_download_bytes=1_000,
        mock_print_delay_seconds=0.1,
        mock_print_failure=False,
        download_timeout_seconds=5,
        heartbeat_interval_seconds=30,
        ws_reconnect_max_delay_seconds=4,
        retry_max_attempts=3,
        retry_base_delay_seconds=1.0,
        retry_max_delay_seconds=30.0,
        cups_command_timeout_seconds=30.0,
        job_poll_interval_seconds=1.0,
    )
    client = WebSocketClient(settings, jm)
    delay = 1.0
    max_delay = 4.0
    steps = []
    for _ in range(3):
        steps.append(delay)
        delay = min(delay * 2, max_delay)
    assert steps == [1.0, 2.0, 4.0]
    db.close()
