"""QuickPrint Pi Agent entry point."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from app import __version__
from app.config import ensure_runtime_directories, load_settings
from app.database import init_db
from app.downloader import Downloader
from app.health import collect_health, set_agent_start_time
from app.job_manager import JobManager
from app.logger import get_logger, setup_logging
from app.printer import create_printer
from app.retry import RetryPolicy
from app.websocket_client import WebSocketClient

log = get_logger("main")


class _HealthHolder:
    last_health = None


async def _run() -> None:
    set_agent_start_time()
    settings = load_settings()
    setup_logging(settings.log_level)
    ensure_runtime_directories(settings)

    log.info(
        "Starting QuickPrint Pi Agent version=%s env=%s printer_mode=%s",
        __version__,
        settings.agent_env,
        settings.printer_mode,
    )

    db = init_db(settings.database_path)
    printer = create_printer(settings)
    downloader = Downloader(
        incoming_dir=settings.incoming_dir,
        max_bytes=settings.max_download_bytes,
        timeout_seconds=settings.download_timeout_seconds,
    )

    retry_policy = RetryPolicy(
        max_attempts=settings.retry_max_attempts,
        base_delay_seconds=settings.retry_base_delay_seconds,
        max_delay_seconds=settings.retry_max_delay_seconds,
    )

    job_manager = JobManager(
        db=db,
        downloader=downloader,
        printer=printer,
        processing_dir=settings.processing_dir,
        completed_dir=settings.completed_dir,
        failed_dir=settings.failed_dir,
        incoming_dir=settings.incoming_dir,
        poll_interval_seconds=settings.job_poll_interval_seconds,
        retry_policy=retry_policy,
    )
    health_holder = _HealthHolder()
    ws_client = WebSocketClient(settings, job_manager, health_provider=health_holder)

    job_manager.start()
    await job_manager.recover_unfinished_jobs()
    ws_client.start()

    health_holder.last_health = await collect_health(
        settings.job_directory.parent,
        printer,
        ws_client.state if settings.backend_ws_url else None,
        job_manager=job_manager,
        printer_mode=settings.printer_mode,
    )
    log.info(
        "Health version=%s disk_free=%s%% memory_mb=%s printer_ok=%s backend=%s jobs=%s",
        health_holder.last_health.agent_version,
        health_holder.last_health.disk_free_percent,
        health_holder.last_health.memory_available_mb,
        health_holder.last_health.printer_ok,
        health_holder.last_health.backend_connection,
        health_holder.last_health.non_terminal_job_count,
    )

    stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        log.info("Shutdown requested")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    await stop_event.wait()

    log.info("Agent shutting down")
    await ws_client.stop()
    await job_manager.stop()
    db.close()
    log.info("Agent stopped")


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
