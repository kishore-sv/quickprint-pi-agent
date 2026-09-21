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
from app.logger import get_logger, job_context, setup_logging
from app.printer import create_printer
from app.retry import RetryPolicy
from app.websocket_client import WebSocketClient

log = get_logger("main")


class _HealthHolder:
    last_health = None
    last_telemetry = None


async def _log_cups_startup(printer, settings) -> None:
    if settings.printer_mode != "cups":
        return
    server = settings.cups_server or "local"
    log.info("CUPS probe server=%s printer=%s", server, settings.cups_printer_name)
    try:
        info = await printer.get_printer_info()
        scheduler = info.get("cups_scheduler_running", False)
        available = info.get("available", False)
        enabled = info.get("enabled", False)
        accepting = info.get("accepting_jobs", False)
        log.info(
            "CUPS status scheduler=%s queue_exists=%s enabled=%s accepting=%s",
            scheduler,
            available,
            enabled,
            accepting,
        )
        if not available:
            log.warning(
                "Configured CUPS printer not found printer=%s",
                settings.cups_printer_name,
            )
        elif not accepting:
            log.warning(
                "CUPS printer not accepting jobs printer=%s",
                settings.cups_printer_name,
            )
    except Exception as e:
        log.warning("CUPS startup probe failed: %s", e)


async def _health_refresh_loop(
    health_holder: _HealthHolder,
    settings,
    printer,
    ws_client: WebSocketClient,
    job_manager: JobManager,
    stop_event: asyncio.Event,
) -> None:
    interval = settings.health_refresh_interval_seconds
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass
        try:
            health_holder.last_health = await collect_health(
                settings.job_directory.parent,
                printer,
                ws_client.state if settings.backend_ws_url else None,
                job_manager=job_manager,
                printer_mode=settings.printer_mode,
                cups_printer_name=settings.cups_printer_name or None,
                telemetry_snapshot=health_holder.last_telemetry,
            )
        except Exception:
            log.warning("Health refresh failed")


async def _run() -> None:
    set_agent_start_time()
    settings = load_settings()
    setup_logging(settings.log_level)
    ensure_runtime_directories(settings)

    log.info(
        "Agent started version=%s env=%s printer_mode=%s agent_id=%s",
        __version__,
        settings.agent_env,
        settings.printer_mode,
        settings.agent_id or "dev",
    )

    db = init_db(settings.database_path)
    printer = create_printer(settings)
    await _log_cups_startup(printer, settings)

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

    health_holder = _HealthHolder()

    async def _physical_completion_ready(cups_job_id: str) -> tuple[bool, str]:
        """CUPS printer idle is enforced in JobManager._evaluate_physical_completion."""
        if settings.printer_mode != "cups":
            return True, "non_cups"
        return True, "printer_idle"

    telemetry_service = None

    async def _publish_printer_before_job_complete() -> None:
        if telemetry_service is not None:
            await telemetry_service.publish_physical_state(force=True)

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
        physical_completion_checker=_physical_completion_ready
        if settings.printer_mode == "cups"
        else None,
        before_job_completed=_publish_printer_before_job_complete,
        physical_completion_stable_seconds=(
            settings.physical_completion_stable_seconds
            if settings.printer_mode == "cups"
            else 0.0
        ),
    )
    ws_client = WebSocketClient(settings, job_manager, health_provider=health_holder)

    if settings.printer_telemetry_enabled:
        from app.printer_telemetry.monitor import MockPrinterMonitor, PrinterMonitor
        from app.printer_telemetry.service import PrinterTelemetryService

        if settings.printer_mode == "mock":
            monitor = MockPrinterMonitor(
                printer_name=settings.cups_printer_name or "mock-printer"
            )
        else:
            monitor = PrinterMonitor(
                settings.cups_printer_name,
                command_timeout_seconds=settings.cups_command_timeout_seconds,
                cups_server=settings.cups_server or None,
                hplip_enabled=settings.printer_hplip_fallback_enabled,
                job_printing_hint=job_manager.has_active_print_job,
                active_job_id_provider=job_manager.current_job_id,
            )
        telemetry_service = PrinterTelemetryService(
            monitor,
            ws_client,
            settings.agent_id or "dev",
            poll_interval_seconds=settings.printer_telemetry_interval_seconds,
            heartbeat_seconds=settings.printer_telemetry_heartbeat_seconds,
            on_snapshot=lambda snap: setattr(health_holder, "last_telemetry", snap),
        )
        ws_client.set_telemetry_service(telemetry_service)
        await telemetry_service.publish_physical_state(force=True)

    job_manager.start()
    await job_manager.recover_unfinished_jobs()
    ws_client.start()
    if telemetry_service is not None:
        telemetry_service.start()

    health_holder.last_health = await collect_health(
        settings.job_directory.parent,
        printer,
        ws_client.state if settings.backend_ws_url else None,
        job_manager=job_manager,
        printer_mode=settings.printer_mode,
        cups_printer_name=settings.cups_printer_name or None,
        telemetry_snapshot=health_holder.last_telemetry,
    )
    snap = health_holder.last_health
    log.info(
        "Health %s printer_ok=%s cups_available=%s backend=%s jobs=%s message=%s",
        job_context(status="healthy" if snap.process_ok else "degraded"),
        snap.printer_ok,
        snap.cups_available,
        snap.backend_connection,
        snap.non_terminal_job_count,
        snap.message or "ok",
    )

    stop_event = asyncio.Event()
    health_task = asyncio.create_task(
        _health_refresh_loop(
            health_holder, settings, printer, ws_client, job_manager, stop_event
        )
    )

    def _request_shutdown() -> None:
        log.info("Shutdown requested")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    await stop_event.wait()

    log.info("Agent shutting down")
    health_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await health_task
    if telemetry_service is not None:
        await telemetry_service.stop()
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
