"""Tests for PrinterTelemetryService emission rules."""

import asyncio

import pytest

from app.printer_telemetry.monitor import MockPrinterMonitor
from app.printer_telemetry.service import PrinterTelemetryService
from app.printer_telemetry.types import DisplayState


@pytest.mark.asyncio
async def test_emits_on_first_snapshot():
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monitor = MockPrinterMonitor()
    svc = PrinterTelemetryService(
        monitor,
        None,
        "agent-1",
        poll_interval_seconds=0.05,
        heartbeat_seconds=10.0,
        send_callback=capture,
    )
    svc.start()
    await asyncio.sleep(0.15)
    await svc.stop()
    assert len(sent) >= 1
    assert sent[0]["display_state"] == DisplayState.READY.value
    assert sent[0]["sequence"] >= 1


@pytest.mark.asyncio
async def test_heartbeat_increments_sequence():
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monitor = MockPrinterMonitor()
    svc = PrinterTelemetryService(
        monitor,
        None,
        "agent-1",
        poll_interval_seconds=0.05,
        heartbeat_seconds=0.08,
        send_callback=capture,
    )
    svc.start()
    await asyncio.sleep(0.25)
    await svc.stop()
    sequences = [m["sequence"] for m in sent]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
