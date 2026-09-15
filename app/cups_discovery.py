"""Parse CUPS lpstat output for printer discovery."""

from __future__ import annotations


def parse_lpstat_printer_status(stdout: str) -> dict[str, bool | str]:
    """Parse `lpstat -p <queue>` first line into structured flags."""
    line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    lower = line.lower()
    result: dict[str, bool | str] = {
        "status_line": line,
        "exists": bool(line),
        "enabled": True,
        "accepting_jobs": True,
        "idle": False,
        "printing": False,
    }
    if not line:
        result["exists"] = False
        return result
    if "disabled" in lower:
        result["enabled"] = False
    if "not accepting" in lower:
        result["accepting_jobs"] = False
    elif "accepting jobs" in lower:
        result["accepting_jobs"] = True
    if "printing" in lower:
        result["printing"] = True
    if "idle" in lower:
        result["idle"] = True
    return result
