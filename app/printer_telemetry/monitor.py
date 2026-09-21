"""Orchestrate printer adapters into a normalized snapshot."""

from __future__ import annotations

from typing import Callable

from app.cups import _build_runner_env
from app.cups_command import CupsCommandRunner
from app.logger import get_logger
from app.models import utc_now_iso
from app.printer_telemetry.adapters.cups_ipp import CupsIppAdapter
from app.printer_telemetry.adapters.hplip import HplipAdapter
from app.printer_telemetry.normalize import normalize_probe, unknown_snapshot
from app.printer_telemetry.types import AdapterProbeResult, PrinterTelemetrySnapshot

log = get_logger("printer_telemetry.monitor")


class PrinterMonitor:
    def __init__(
        self,
        printer_name: str,
        cups_runner: CupsCommandRunner | None = None,
        command_timeout_seconds: float = 30.0,
        cups_server: str | None = None,
        hplip_enabled: bool = True,
        job_printing_hint: Callable[[], bool] | None = None,
        active_job_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._printer_name = printer_name
        runner = cups_runner or _build_runner_env(cups_server)
        self._cups = CupsIppAdapter(
            printer_name,
            runner,
            command_timeout_seconds,
        )
        self._hplip = HplipAdapter(enabled=hplip_enabled)
        self._job_printing_hint = job_printing_hint or (lambda: False)
        self._active_job_id = active_job_id_provider or (lambda: None)

    async def collect_snapshot(self) -> PrinterTelemetrySnapshot:
        last_probe_at = utc_now_iso()
        try:
            base = AdapterProbeResult()
            merged = await self._cups.probe(base)
            merged = await self._hplip.probe(merged)
            job_hint = self._job_printing_hint()
            active_job = self._active_job_id()
            snap = normalize_probe(
                merged,
                printer_name=self._printer_name,
                last_probe_at=last_probe_at,
                active_job_id=active_job,
                job_printing_hint=job_hint,
            )
            return snap
        except Exception as e:
            log.warning("Printer telemetry probe failed: %s", e)
            return unknown_snapshot(self._printer_name, last_probe_at)


class MockPrinterMonitor:
    """Deterministic telemetry for PRINTER_MODE=mock."""

    def __init__(
        self,
        printer_name: str = "mock-printer",
        display_state: str = "READY",
    ) -> None:
        self._printer_name = printer_name
        self._display = display_state

    async def collect_snapshot(self) -> PrinterTelemetrySnapshot:
        from app.printer_telemetry.types import (
            ConnectionState,
            DisplayState,
            OperationalState,
            PrinterCapabilities,
            PrinterTelemetrySnapshot,
        )

        last_probe_at = utc_now_iso()
        if self._display == "PRINTING":
            return PrinterTelemetrySnapshot(
                printer_name=self._printer_name,
                connection_state=ConnectionState.ONLINE,
                operational_state=OperationalState.PRINTING,
                display_state=DisplayState.PRINTING,
                reasons=[],
                raw_reasons=[],
                last_probe_at=last_probe_at,
                capabilities=PrinterCapabilities(
                    manufacturer="Mock",
                    model="Printer",
                    connection_type="unknown",
                ),
            )
        return PrinterTelemetrySnapshot(
            printer_name=self._printer_name,
            connection_state=ConnectionState.ONLINE,
            operational_state=OperationalState.IDLE,
            display_state=DisplayState.READY,
            reasons=[],
            raw_reasons=[],
            last_probe_at=last_probe_at,
            capabilities=PrinterCapabilities(
                manufacturer="Mock",
                model="Printer",
                connection_type="unknown",
            ),
        )
