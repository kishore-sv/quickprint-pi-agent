"""Agent health checks."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.websocket_client import ConnectionState

if TYPE_CHECKING:
    from app.printer import Printer


@dataclass
class HealthSnapshot:
    process_ok: bool
    disk_free_percent: float | None
    memory_available_mb: float | None
    backend_connection: str
    printer_ok: bool
    message: str = ""


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
) -> HealthSnapshot:
    printer_ok = await printer.health_check()
    conn = backend_state.value if backend_state else "DISABLED"
    return HealthSnapshot(
        process_ok=True,
        disk_free_percent=_disk_free_percent(project_root),
        memory_available_mb=_memory_available_mb(),
        backend_connection=conn,
        printer_ok=printer_ok,
    )
