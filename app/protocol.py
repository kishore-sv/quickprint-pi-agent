"""WebSocket message protocol (internal schema, adaptable to backend)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.models import AssignedJob


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
    return AssignedJob.from_protocol_payload(msg.payload)


def build_outbound(msg_type: OutboundType, **fields: Any) -> str:
    body: dict[str, Any] = {"type": msg_type.value}
    body.update(fields)
    return json.dumps(body)


def status_message_for_job_status(status: str, job_id: str, **extra: Any) -> str:
    mapping = {
        "RECEIVED": OutboundType.JOB_RECEIVED,
        "DOWNLOADING": OutboundType.JOB_DOWNLOADING,
        "READY": OutboundType.JOB_READY,
        "SUBMITTED": OutboundType.JOB_SUBMITTED,
        "PRINTING": OutboundType.JOB_PRINTING,
        "COMPLETED": OutboundType.JOB_COMPLETED,
        "FAILED": OutboundType.JOB_FAILED,
        "CANCELLED": OutboundType.JOB_FAILED,
    }
    outbound = mapping.get(status)
    if outbound is None:
        return build_outbound(OutboundType.JOB_RECEIVED, job_id=job_id, **extra)
    return build_outbound(outbound, job_id=job_id, **extra)


def build_heartbeat(agent_id: str) -> str:
    return build_outbound(OutboundType.AGENT_HEARTBEAT, agent_id=agent_id)
