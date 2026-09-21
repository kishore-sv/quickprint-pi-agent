"""Agent health checks."""

from __future__ import annotations

import os
import shutil
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app import __version__

if TYPE_CHECKING:
    from app.job_manager import JobManager
    from app.printer import Printer
    from app.websocket_client import ConnectionState

_AGENT_START_MONOTONIC = time.monotonic()


def set_agent_start_time() -> None:
    global _AGENT_START_MONOTONIC
    _AGENT_START_MONOTONIC = time.monotonic()


def uptime_seconds() -> float:
    return round(time.monotonic() - _AGENT_START_MONOTONIC, 2)


@dataclass
class HealthSnapshot:
    process_ok: bool
    agent_version: str
    hostname: str
    uptime_seconds: float
    disk_free_percent: float | None
    memory_available_mb: float | None
    backend_connection: str
    printer_ok: bool
    printer_available: bool
    cups_available: bool | None
    cups_printer_name: str | None
    printer_enabled: bool | None
    printer_accepting_jobs: bool | None
    cups_scheduler_running: bool | None
    non_terminal_job_count: int
    current_job_id: str | None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "process_ok": self.process_ok,
            "agent_version": self.agent_version,
            "hostname": self.hostname,
            "uptime_seconds": self.uptime_seconds,
            "disk_free_percent": self.disk_free_percent,
            "memory_available_mb": self.memory_available_mb,
            "backend_connection": self.backend_connection,
            "printer_ok": self.printer_ok,
            "printer_available": self.printer_available,
            "cups_available": self.cups_available,
            "cups_printer_name": self.cups_printer_name,
            "printer_enabled": self.printer_enabled,
            "printer_accepting_jobs": self.printer_accepting_jobs,
            "cups_scheduler_running": self.cups_scheduler_running,
            "non_terminal_job_count": self.non_terminal_job_count,
            "current_job_id": self.current_job_id,
            "message": self.message,
        }


def _disk_free_percent(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path)
        if usage.total == 0:
            return None
        return round(usage.free / usage.total * 100.0, 2)
    except OSError:
        return None


def _memory_available_mb() -> float | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024.0, 2)
        except (OSError, ValueError, IndexError):
            return None
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page_size / (1024 * 1024), 2)
    except (AttributeError, ValueError, OSError):
        return None


async def collect_health(
    project_root: Path,
    printer: Printer,
    backend_state: ConnectionState | None,
    job_manager: JobManager | None = None,
    printer_mode: str = "mock",
    cups_printer_name: str | None = None,
    telemetry_snapshot: object | None = None,
) -> HealthSnapshot:
    printer_ok = False
    printer_available = False
    cups_available: bool | None = None
    printer_enabled: bool | None = None
    printer_accepting_jobs: bool | None = None
    cups_scheduler_running: bool | None = None
    message_parts: list[str] = []

    telemetry_used = False
    if telemetry_snapshot is not None:
        try:
            from app.printer_telemetry.types import ConnectionState as TConn
            from app.printer_telemetry.types import DisplayState as TDisp

            conn = getattr(telemetry_snapshot, "connection_state", None)
            disp = getattr(telemetry_snapshot, "display_state", None)
            if conn is not None and disp is not None:
                printer_ok = conn == TConn.ONLINE and disp in (
                    TDisp.READY,
                    TDisp.PRINTING,
                )
                printer_available = conn == TConn.ONLINE
                telemetry_used = True
        except Exception:
            telemetry_used = False

    try:
        if not telemetry_used:
            printer_ok = await printer.health_check()
            printer_available = await printer.is_available()
        info = await printer.get_printer_info()
        if printer_mode == "cups":
            cups_available = bool(info.get("cups_scheduler_running"))
            printer_enabled = bool(info.get("enabled"))
            printer_accepting_jobs = bool(info.get("accepting_jobs"))
            cups_scheduler_running = bool(info.get("cups_scheduler_running"))
            if not cups_available:
                message_parts.append("CUPS scheduler unavailable")
            elif not info.get("available"):
                message_parts.append(f"CUPS queue missing: {cups_printer_name or info.get('name')}")
            elif not printer_enabled:
                message_parts.append("CUPS queue disabled")
            elif not printer_accepting_jobs:
                message_parts.append("CUPS queue not accepting jobs")
    except Exception:
        message_parts.append("Printer health check failed")

    conn = backend_state.value if backend_state else "DISABLED"
    non_terminal = 0
    current_job: str | None = None
    if job_manager is not None:
        try:
            non_terminal = job_manager.non_terminal_job_count()
            current_job = job_manager.current_job_id()
        except Exception:
            pass

    hostname = "unknown"
    try:
        hostname = socket.gethostname()
    except OSError:
        pass

    process_ok = printer_ok or printer_mode == "mock"
    if printer_mode == "cups" and not printer_ok:
        process_ok = True  # agent stays up; printer may be unconfigured

    return HealthSnapshot(
        process_ok=process_ok,
        agent_version=__version__,
        hostname=hostname,
        uptime_seconds=uptime_seconds(),
        disk_free_percent=_disk_free_percent(project_root),
        memory_available_mb=_memory_available_mb(),
        backend_connection=conn,
        printer_ok=printer_ok,
        printer_available=printer_available,
        cups_available=cups_available,
        cups_printer_name=cups_printer_name,
        printer_enabled=printer_enabled,
        printer_accepting_jobs=printer_accepting_jobs,
        cups_scheduler_running=cups_scheduler_running,
        non_terminal_job_count=non_terminal,
        current_job_id=current_job,
        message="; ".join(message_parts),
    )
