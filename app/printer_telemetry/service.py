"""Polling loop and WebSocket emission for printer telemetry."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import TYPE_CHECKING, Awaitable, Callable

from app.logger import get_logger
from app.models import utc_now_iso
from app.printer_telemetry.types import PrinterTelemetrySnapshot

if TYPE_CHECKING:
    from app.websocket_client import WebSocketClient

log = get_logger("printer_telemetry.service")


class PrinterTelemetryService:
    def __init__(
        self,
        monitor: object,
        ws_client: WebSocketClient | None,
        agent_id: str,
        poll_interval_seconds: float = 3.0,
        heartbeat_seconds: float = 10.0,
        send_callback: Callable[[dict], Awaitable[None]] | None = None,
        on_snapshot: Callable[[PrinterTelemetrySnapshot], None] | None = None,
    ) -> None:
        self._monitor = monitor
        self._ws = ws_client
        self._agent_id = agent_id
        self._poll_interval = poll_interval_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._send_callback = send_callback
        self._on_snapshot = on_snapshot
        self._sequence = 0
        self._last_snapshot: PrinterTelemetrySnapshot | None = None
        self._last_heartbeat_monotonic = 0.0
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def last_snapshot(self) -> PrinterTelemetrySnapshot | None:
        return self._last_snapshot

    def start(self) -> None:
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def publish_physical_state(
        self, *, force: bool = False
    ) -> PrinterTelemetrySnapshot:
        """Re-probe printer without job hint; publish when state changes or force."""
        collect_physical = getattr(self._monitor, "collect_snapshot_physical", None)
        if collect_physical is not None:
            snap = await collect_physical()
        else:
            snap = await self._monitor.collect_snapshot()
        prev = self._last_snapshot
        self._last_snapshot = snap
        if self._on_snapshot is not None:
            self._on_snapshot(snap)
        changed = prev is None or snap.state_key() != prev.state_key()
        if force or changed:
            if prev is not None and changed:
                log.info(
                    "Printer telemetry physical publish: %s → %s (display %s → %s)",
                    prev.connection_state.value,
                    snap.connection_state.value,
                    prev.display_state.value,
                    snap.display_state.value,
                )
            await self._emit(snap, is_heartbeat=False, force=force)
        return snap

    async def flush_on_reconnect(self) -> None:
        await self.publish_physical_state(force=True)

    async def _run_loop(self) -> None:
        import time

        while not self._stop_event.is_set():
            try:
                snap = await self._monitor.collect_snapshot()
                prev = self._last_snapshot
                changed = prev is None or snap.state_key() != prev.state_key()
                self._last_snapshot = snap
                if self._on_snapshot is not None:
                    self._on_snapshot(snap)

                if changed:
                    if prev is not None:
                        log.info(
                            "Printer telemetry changed: %s → %s (display %s → %s)",
                            prev.connection_state.value,
                            snap.connection_state.value,
                            prev.display_state.value,
                            snap.display_state.value,
                        )
                    await self._emit(snap, is_heartbeat=False)

                now = time.monotonic()
                if now - self._last_heartbeat_monotonic >= self._heartbeat_seconds:
                    self._last_heartbeat_monotonic = now
                    if not changed:
                        await self._emit(snap, is_heartbeat=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Telemetry loop error")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval
                )
                break
            except asyncio.TimeoutError:
                pass

    async def _emit(
        self,
        snap: PrinterTelemetrySnapshot,
        *,
        is_heartbeat: bool,
        force: bool = False,
    ) -> None:
        self._sequence += 1
        payload = snap.to_wire_dict(
            agent_id=self._agent_id,
            event_id=str(uuid.uuid4()),
            sequence=self._sequence,
            timestamp=utc_now_iso(),
            is_heartbeat=is_heartbeat,
        )
        if self._send_callback is not None:
            await self._send_callback(payload)
            return
        if self._ws is None:
            return
        await self._ws.send_telemetry(payload, is_heartbeat=is_heartbeat)
