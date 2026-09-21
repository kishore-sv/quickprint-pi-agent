"""Adapter protocol for printer probes."""

from __future__ import annotations

from typing import Protocol

from app.printer_telemetry.types import AdapterProbeResult


class PrinterAdapter(Protocol):
    async def probe(self, base: AdapterProbeResult) -> AdapterProbeResult:
        """Merge adapter findings into base probe result."""
        ...
