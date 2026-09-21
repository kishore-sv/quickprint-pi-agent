"""Parse CUPS lpstat job state without false 'completed' matches."""

from __future__ import annotations

import re

from app.printer import PrinterJobState

# Driver/spooler phrases that mean the job is still active on the queue.
_ACTIVE_WHILE_SUBSTRING = (
    "rendering completed",
    "spooling completed",
    "data completed",
)

_JOB_STATE_LINE = re.compile(r"^\s*job-state:\s*(.+)$", re.IGNORECASE)
_JOB_STATE_REASONS = re.compile(r"^\s*job-state-reasons:\s*(.+)$", re.IGNORECASE)

_IPP_STATE_TO_PRINTER: dict[str, PrinterJobState] = {
    "pending": PrinterJobState.PENDING,
    "pending-held": PrinterJobState.PENDING,
    "processing": PrinterJobState.PRINTING,
    "processing-stopped": PrinterJobState.PRINTING,
    "canceled": PrinterJobState.CANCELLED,
    "cancelled": PrinterJobState.CANCELLED,
    "aborted": PrinterJobState.FAILED,
    "completed": PrinterJobState.COMPLETED,
}


def parse_lpstat_long_job(stdout: str) -> tuple[PrinterJobState | None, list[str]]:
    """Parse `lpstat -l -o <job-id>` for job-state and reasons."""
    state: PrinterJobState | None = None
    reasons: list[str] = []
    for line in stdout.splitlines():
        m = _JOB_STATE_LINE.match(line)
        if m:
            key = m.group(1).strip().lower()
            state = _IPP_STATE_TO_PRINTER.get(key, PrinterJobState.UNKNOWN)
            continue
        m = _JOB_STATE_REASONS.match(line)
        if m:
            raw = m.group(1).strip()
            if raw.lower() not in ("none", ""):
                reasons = [p.strip() for p in raw.split(",") if p.strip()]
    return state, reasons


def parse_lpstat_short_job_line(line: str) -> PrinterJobState:
    """
    Parse a single line from `lpstat -o <queue>`.

    Do not treat substrings like 'Rendering completed' or 'Spooling completed'
    as terminal CUPS completion.
    """
    lower = line.lower().strip()
    if not lower:
        return PrinterJobState.UNKNOWN

    for phrase in _ACTIVE_WHILE_SUBSTRING:
        if phrase in lower:
            return PrinterJobState.PRINTING

    parts = line.split()
    if parts:
        last_token = parts[-1].lower()
        mapped = _IPP_STATE_TO_PRINTER.get(last_token)
        if mapped is not None:
            return mapped

    if re.search(r"\b(processing|printing)\b", lower):
        return PrinterJobState.PRINTING
    if re.search(r"\b(pending|held|queued)\b", lower):
        return PrinterJobState.PENDING
    if re.search(r"\b(canceled|cancelled)\b", lower):
        return PrinterJobState.CANCELLED
    if re.search(r"\baborted\b", lower):
        return PrinterJobState.FAILED
    if re.search(r"\bcompleted\b", lower):
        return PrinterJobState.COMPLETED

    return PrinterJobState.UNKNOWN
