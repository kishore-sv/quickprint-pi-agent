"""Agent health checks."""

from __future__ import annotations

import os
import shutil
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app import __version__

if TYPE_CHECKING:
    from app.database import Database
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
            "cups_scheduler_running": self.cups_scheduler_running,
            "non_terminal_job_count": self.non_terminal_job_count,
            "current_job_id": self.current_job_id,
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
) -> HealthSnapshot:
    printer_ok = False
    printer_available = False
    cups_scheduler_running: bool | None = None
    try:
        printer_ok = await printer.health_check()
        printer_available = await printer.is_available()
        if printer_mode == "cups":
            info = await printer.get_printer_info()
            if "cups_scheduler_running" in info:
                cups_scheduler_running = bool(info["cups_scheduler_running"])
    except Exception:
        pass

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

    return HealthSnapshot(
        process_ok=True,
        agent_version=__version__,
        hostname=hostname,
        uptime_seconds=uptime_seconds(),
        disk_free_percent=_disk_free_percent(project_root),
        memory_available_mb=_memory_available_mb(),
        backend_connection=conn,
        printer_ok=printer_ok,
        printer_available=printer_available,
        cups_scheduler_running=cups_scheduler_running,
        non_terminal_job_count=non_terminal,
        current_job_id=current_job,
    )
