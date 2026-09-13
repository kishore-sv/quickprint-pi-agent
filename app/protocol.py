"""WebSocket message protocol (internal schema, adaptable to backend)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from app.models import AssignedJob
from app.page_range import validate_page_range


class InboundType(str, Enum):
    JOB_ASSIGNED = "job.assigned"
    JOB_CANCEL = "job.cancel"
    PING = "ping"


class OutboundType(str, Enum):
    JOB_RECEIVED = "job.received"
    JOB_DOWNLOADING = "job.downloading"
    JOB_READY = "job.ready"
    JOB_SUBMITTED = "job.submitted"
    JOB_PRINTING = "job.printing"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    AGENT_HEARTBEAT = "agent.heartbeat"
    PONG = "pong"


@dataclass
class InboundMessage:
    type: InboundType
    payload: dict[str, Any]


class ProtocolError(Exception):
    """Invalid protocol message."""


def validate_job_assigned_payload(payload: dict[str, Any]) -> None:
    job_id = payload.get("job_id")
    if not job_id or not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("job.assigned requires non-empty string job_id")

    file_url = payload.get("file_url")
    if not file_url or not isinstance(file_url, str) or not file_url.strip():
        raise ValueError("job.assigned requires non-empty string file_url")
    parsed = urlparse(file_url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("file_url must use http or https")

    filename = payload.get("filename")
    if filename is not None and not isinstance(filename, str):
        raise ValueError("filename must be a string")

    settings_raw = payload.get("print_settings") or {}
    if not isinstance(settings_raw, dict):
        raise ValueError("print_settings must be an object")

    copies = settings_raw.get("copies", 1)
    try:
        copies_int = int(copies)
    except (TypeError, ValueError):
        raise ValueError("copies must be an integer") from None
    if copies_int < 1 or copies_int > 99:
        raise ValueError("copies must be between 1 and 99")

    page_range = settings_raw.get("page_range")
    if page_range is not None:
        if not isinstance(page_range, str):
            raise ValueError("page_range must be a string")
        validate_page_range(page_range)


def parse_message(raw: str) -> InboundMessage:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ProtocolError("Invalid JSON") from e
    if not isinstance(data, dict):
        raise ProtocolError("Message must be a JSON object")
    msg_type = data.get("type")
    if not isinstance(msg_type, str):
        raise ProtocolError("Missing message type")
    try:
        inbound_type = InboundType(msg_type)
    except ValueError as e:
        raise ProtocolError(f"Unknown message type: {msg_type}") from e
    return InboundMessage(type=inbound_type, payload=data)


def assigned_job_from_message(msg: InboundMessage) -> AssignedJob:
    if msg.type != InboundType.JOB_ASSIGNED:
        raise ProtocolError("Not a job.assigned message")
    validate_job_assigned_payload(msg.payload)
    return AssignedJob.from_protocol_payload(msg.payload)


def build_outbound(msg_type: OutboundType, **fields: Any) -> str:
    body: dict[str, Any] = {"type": msg_type.value}
    body.update(fields)
    return json.dumps(body)


def status_message_for_job_status(
    status: str,
    job_id: str,
    *,
    agent_id: str | None = None,
    timestamp: str | None = None,
    cups_job_id: str | None = None,
    **extra: Any,
) -> str:
    mapping = {
        "RECEIVED": OutboundType.JOB_RECEIVED,
        "DOWNLOADING": OutboundType.JOB_DOWNLOADING,
        "READY": OutboundType.JOB_READY,
        "SUBMITTED": OutboundType.JOB_SUBMITTED,
        "PRINTING": OutboundType.JOB_PRINTING,
        "COMPLETED": OutboundType.JOB_COMPLETED,
        "FAILED": OutboundType.JOB_FAILED,
        "CANCELLED": OutboundType.JOB_FAILED,
        "RETRY_WAITING": OutboundType.JOB_FAILED,
    }
    fields: dict[str, Any] = {"job_id": job_id}
    if agent_id:
        fields["agent_id"] = agent_id
    if timestamp:
        fields["timestamp"] = timestamp
    if cups_job_id:
        fields["cups_job_id"] = cups_job_id
    fields.update(extra)
    outbound = mapping.get(status)
    if outbound is None:
        return build_outbound(OutboundType.JOB_RECEIVED, **fields)
    return build_outbound(outbound, **fields)


def build_heartbeat(agent_id: str, health: dict[str, Any] | None = None) -> str:
    fields: dict[str, Any] = {"agent_id": agent_id}
    if health:
        fields["health"] = health
    return build_outbound(OutboundType.AGENT_HEARTBEAT, **fields)
