"""Domain models and job state machine."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DOWNLOADING = "DOWNLOADING"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRY_WAITING = "RETRY_WAITING"


TERMINAL_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)

ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.RECEIVED: frozenset(
        {JobStatus.DOWNLOADING, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.DOWNLOADING: frozenset(
        {JobStatus.READY, JobStatus.FAILED, JobStatus.RETRY_WAITING}
    ),
    JobStatus.READY: frozenset({JobStatus.SUBMITTED, JobStatus.FAILED}),
    JobStatus.SUBMITTED: frozenset(
        {JobStatus.PRINTING, JobStatus.COMPLETED, JobStatus.FAILED}
    ),
    JobStatus.PRINTING: frozenset({JobStatus.COMPLETED, JobStatus.FAILED}),
    JobStatus.RETRY_WAITING: frozenset(
        {JobStatus.DOWNLOADING, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Illegal job status transition."""


def assert_transition(current: JobStatus, new: JobStatus) -> None:
    if current == new:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if new not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {current.value} to {new.value}"
        )


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class PrintSettings:
    copies: int = 1
    page_range: str | None = None
    color_mode: str = "bw"
    paper_size: str = "A4"
    duplex: bool = False
    pages_per_sheet: int = 1
    order: str = "normal"
    orientation: str = "auto"
    fit_to_page: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PrintSettings:
        return cls(
            copies=int(data.get("copies", 1)),
            page_range=data.get("page_range"),
            color_mode=str(data.get("color_mode", "bw")),
            paper_size=str(data.get("paper_size", "A4")),
            duplex=bool(data.get("duplex", False)),
            pages_per_sheet=int(data.get("pages_per_sheet", 1)),
            order=str(data.get("order", "normal")),
            orientation=str(data.get("orientation", "auto")),
            fit_to_page=bool(data.get("fit_to_page", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssignedJob:
    backend_job_id: str
    file_url: str
    filename: str | None = None
    print_settings: PrintSettings = field(default_factory=PrintSettings)

    @classmethod
    def from_protocol_payload(cls, payload: dict[str, Any]) -> AssignedJob:
        from app.protocol import validate_job_assigned_payload

        validate_job_assigned_payload(payload)
        job_id = payload.get("job_id")
        if not job_id or not isinstance(job_id, str):
            raise ValueError("job.assigned requires string job_id")
        file_url = payload.get("file_url")
        if not file_url or not isinstance(file_url, str):
            raise ValueError("job.assigned requires string file_url")
        settings_raw = payload.get("print_settings") or {}
        if not isinstance(settings_raw, dict):
            raise ValueError("print_settings must be an object")
        filename = payload.get("filename")
        if filename is not None and not isinstance(filename, str):
            raise ValueError("filename must be a string")
        return cls(
            backend_job_id=job_id,
            file_url=file_url,
            filename=filename,
            print_settings=PrintSettings.from_dict(settings_raw),
        )


@dataclass
class JobRecord:
    id: int
    backend_job_id: str
    status: JobStatus
    file_path: str | None
    cups_job_id: str | None
    attempt_count: int
    created_at: str
    updated_at: str
    error_message: str | None
    metadata_json: str | None

    def metadata_dict(self) -> dict[str, Any]:
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except json.JSONDecodeError:
            return {}
