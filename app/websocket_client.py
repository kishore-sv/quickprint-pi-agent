"""WebSocket client with reconnect and heartbeat."""

from __future__ import annotations

import asyncio
import contextlib
from enum import Enum
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from app.config import Settings
from app.job_manager import JobManager
from app.logger import get_logger
from app.models import JobStatus, utc_now_iso
from app.protocol import (
    InboundType,
    ProtocolError,
    assigned_job_from_message,
    cancel_job_id_from_message,
    build_heartbeat,
    build_outbound,
    parse_message,
    status_message_for_job_status,
)

log = get_logger("websocket_client")

AUTH_HEADER = "Authorization"


class ConnectionState(str, Enum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"


class WebSocketClient:
    def __init__(
        self,
        settings: Settings,
        job_manager: JobManager,
        health_provider: object | None = None,
    ) -> None:
        self._settings = settings
        self._job_manager = job_manager
        self._health_provider = health_provider
        job_manager.set_state_change_callback(self.send_status)
        self._state = ConnectionState.DISCONNECTED
        self._ws: ClientConnection | None = None
        self._task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._pending_statuses: dict[str, tuple[JobStatus, dict[str, Any]]] = {}

    @property
    def state(self) -> ConnectionState:
        return self._state

    def _build_status_message(
        self,
        backend_job_id: str,
        status: JobStatus,
        extra: dict[str, Any] | None = None,
    ) -> str:
        fields = dict(extra or {})
        cups_job_id = fields.pop("cups_job_id", None)
        if cups_job_id is not None and not isinstance(cups_job_id, str):
            cups_job_id = None
        agent_id = self._settings.agent_id or None
        return status_message_for_job_status(
            status.value,
            backend_job_id,
            agent_id=agent_id,
            timestamp=utc_now_iso(),
            cups_job_id=cups_job_id,
            **fields,
        )

    async def send_status(
        self,
        backend_job_id: str,
        status: JobStatus,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(extra or {})
        if self._ws is None or self._state != ConnectionState.CONNECTED:
            self._pending_statuses[backend_job_id] = (status, payload)
            log.info(
                "Queued status for job=%s status=%s (ws %s)",
                backend_job_id,
                status.value,
                self._state.value,
            )
            return
        msg = self._build_status_message(backend_job_id, status, payload)
        try:
            await self._ws.send(msg)
            log.info(
                "Sent status for job=%s status=%s",
                backend_job_id,
                status.value,
            )
        except Exception:
            log.warning(
                "Failed to send status for job=%s status=%s",
                backend_job_id,
                status.value,
            )
            self._pending_statuses[backend_job_id] = (status, payload)

    async def _flush_pending_statuses(self) -> None:
        if not self._pending_statuses or self._ws is None:
            return
        pending = list(self._pending_statuses.items())
        self._pending_statuses.clear()
        for backend_job_id, (status, extra) in pending:
            msg = self._build_status_message(backend_job_id, status, extra)
            try:
                await self._ws.send(msg)
            except Exception:
                log.warning(
                    "Failed to flush pending status for job=%s", backend_job_id
                )
                self._pending_statuses[backend_job_id] = (status, extra)

    def start(self) -> None:
        if not self._settings.backend_ws_url:
            log.info("BACKEND_WS_URL not set; WebSocket client disabled")
            return
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._state = ConnectionState.DISCONNECTED

    async def _run_forever(self) -> None:
        delay = 1.0
        max_delay = float(self._settings.ws_reconnect_max_delay_seconds)
        while not self._stop_event.is_set():
            try:
                self._state = (
                    ConnectionState.RECONNECTING
                    if self._state != ConnectionState.DISCONNECTED
                    else ConnectionState.CONNECTING
                )
                await self._connect_session()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("WebSocket connection error")
                self._state = ConnectionState.RECONNECTING
            if self._stop_event.is_set():
                break
            log.info("Reconnecting in %.1fs", delay)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, max_delay)

    def _auth_headers(self) -> dict[str, str]:
        if not self._settings.agent_id or not self._settings.agent_secret:
            return {}
        return {
            AUTH_HEADER: f"Bearer {self._settings.agent_id}:{self._settings.agent_secret}"
        }

    async def _connect_session(self) -> None:
        url = self._settings.backend_ws_url
        log.info("Connecting to backend WebSocket")
        extra_headers = self._auth_headers()
        async with websockets.connect(
            url,
            additional_headers=extra_headers or None,
            open_timeout=30,
        ) as ws:
            self._ws = ws
            self._state = ConnectionState.CONNECTED
            log.info("WebSocket connected")
            await self._job_manager.reconcile_backend_status()
            await self._flush_pending_statuses()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            try:
                async for raw in ws:
                    if self._stop_event.is_set():
                        break
                    await self._handle_raw(raw)
            finally:
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._heartbeat_task
                self._ws = None
                self._state = ConnectionState.DISCONNECTED
                log.info("WebSocket disconnected")

    async def _heartbeat_loop(self) -> None:
        interval = self._settings.heartbeat_interval_seconds
        while not self._stop_event.is_set():
            await asyncio.sleep(interval)
            if self._ws and self._state == ConnectionState.CONNECTED:
                try:
                    health_data = None
                    if self._health_provider is not None:
                        snap = getattr(self._health_provider, "last_health", None)
                        if snap is not None and hasattr(snap, "to_dict"):
                            health_data = snap.to_dict()
                    await self._ws.send(
                        build_heartbeat(
                            self._settings.agent_id or "dev", health=health_data
                        )
                    )
                except Exception:
                    log.warning("Heartbeat send failed")

    async def _handle_raw(self, raw: str | bytes) -> None:
        text = raw.decode() if isinstance(raw, bytes) else raw
        try:
            msg = parse_message(text)
        except ProtocolError as e:
            log.warning("Ignoring malformed message: %s", e)
            return

        if msg.type == InboundType.PING:
            if self._ws:
                from app.protocol import OutboundType

                await self._ws.send(build_outbound(OutboundType.PONG))
            return

        if msg.type == InboundType.JOB_ASSIGNED:
            try:
                assigned = assigned_job_from_message(msg)
            except ValueError as e:
                log.warning("Invalid job.assigned: %s", e)
                return
            await self._job_manager.enqueue_assigned(assigned)
            return

        if msg.type == InboundType.JOB_CANCEL:
            try:
                job_id = cancel_job_id_from_message(msg)
            except ValueError as e:
                log.warning("Invalid job.cancel: %s", e)
                return
            log.info("Received job.cancel job_id=%s", job_id)
            await self._job_manager.handle_cancel(job_id)
            return

        log.debug("Unhandled inbound type: %s", msg.type)
