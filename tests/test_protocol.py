"""Protocol parsing tests."""

import json

import pytest

from app.protocol import (
    OutboundType,
    ProtocolError,
    assigned_job_from_message,
    build_outbound,
    parse_message,
    status_message_for_job_status,
)


def test_parse_job_assigned():
    raw = json.dumps(
        {
            "type": "job.assigned",
            "job_id": "j1",
            "file_url": "https://example.com/f.pdf",
            "print_settings": {"copies": 2, "color_mode": "bw"},
        }
    )
    msg = parse_message(raw)
    job = assigned_job_from_message(msg)
    assert job.backend_job_id == "j1"
    assert job.print_settings.copies == 2


def test_invalid_job_assigned_url():
    raw = json.dumps(
        {
            "type": "job.assigned",
            "job_id": "j1",
            "file_url": "ftp://bad.example.com/f.pdf",
        }
    )
    with pytest.raises(ValueError):
        assigned_job_from_message(parse_message(raw))


def test_malformed_message():
    with pytest.raises(ProtocolError):
        parse_message("not json")
    with pytest.raises(ProtocolError):
        parse_message(json.dumps({"type": "unknown.event"}))


def test_outbound_builders():
    msg = status_message_for_job_status("COMPLETED", "j1")
    data = json.loads(msg)
    assert data["type"] == OutboundType.JOB_COMPLETED.value
    assert data["job_id"] == "j1"

    hb = build_outbound(OutboundType.AGENT_HEARTBEAT, agent_id="a1")
    assert json.loads(hb)["agent_id"] == "a1"
