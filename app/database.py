"""SQLite persistence for local job execution state."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.models import JobRecord, JobStatus, assert_transition, utc_now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backend_job_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    file_path TEXT,
    cups_job_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def init(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def create_job(
        self,
        backend_job_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> JobRecord:
        now = utc_now_iso()
        meta = json.dumps(metadata or {})
        with self._lock:
            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO jobs (
                        backend_job_id, status, file_path, cups_job_id,
                        attempt_count, created_at, updated_at, error_message, metadata_json
                    ) VALUES (?, ?, NULL, NULL, 0, ?, ?, NULL, ?)
                    """,
                    (backend_job_id, JobStatus.RECEIVED.value, now, now, meta),
                )
                self._conn.commit()
                row_id = cur.lastrowid
            except sqlite3.IntegrityError:
                existing = self.get_by_backend_id(backend_job_id)
                if existing is None:
                    raise
                return existing
        return self.get_by_id(row_id)  # type: ignore[arg-type]

    def get_by_id(self, job_id: int) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def get_by_backend_id(self, backend_job_id: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE backend_job_id = ?", (backend_job_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def update_status(
        self,
        backend_job_id: str,
        new_status: JobStatus,
        error_message: str | None = None,
    ) -> JobRecord:
        record = self.get_by_backend_id(backend_job_id)
        if record is None:
            raise KeyError(f"Job not found: {backend_job_id}")
        current = JobStatus(record.status)
        assert_transition(current, new_status)
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs SET status = ?, updated_at = ?, error_message = ?
                WHERE backend_job_id = ?
                """,
                (new_status.value, now, error_message, backend_job_id),
            )
            self._conn.commit()
        updated = self.get_by_backend_id(backend_job_id)
        assert updated is not None
        return updated

    def set_file_path(self, backend_job_id: str, file_path: str) -> None:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET file_path = ?, updated_at = ? WHERE backend_job_id = ?",
                (file_path, now, backend_job_id),
            )
            self._conn.commit()

    def set_cups_job_id(self, backend_job_id: str, cups_job_id: str) -> None:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET cups_job_id = ?, updated_at = ? WHERE backend_job_id = ?",
                (cups_job_id, now, backend_job_id),
            )
            self._conn.commit()

    def merge_metadata(self, backend_job_id: str, updates: dict[str, Any]) -> None:
        record = self.get_by_backend_id(backend_job_id)
        if record is None:
            raise KeyError(f"Job not found: {backend_job_id}")
        meta = record.metadata_dict()
        meta.update(updates)
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs SET metadata_json = ?, updated_at = ?
                WHERE backend_job_id = ?
                """,
                (json.dumps(meta), now, backend_job_id),
            )
            self._conn.commit()

    def increment_attempt(self, backend_job_id: str) -> None:
        now = utc_now_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs SET attempt_count = attempt_count + 1, updated_at = ?
                WHERE backend_job_id = ?
                """,
                (now, backend_job_id),
            )
            self._conn.commit()

    def list_non_terminal_jobs(self) -> list[JobRecord]:
        active = [
            JobStatus.RECEIVED.value,
            JobStatus.DOWNLOADING.value,
            JobStatus.READY.value,
            JobStatus.SUBMITTED.value,
            JobStatus.PRINTING.value,
            JobStatus.RETRY_WAITING.value,
        ]
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(active))})",
                active,
            ).fetchall()
        return [_row_to_record(r) for r in rows]


def init_db(path: Path) -> Database:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(path)
    db.init()
    return db


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        backend_job_id=row["backend_job_id"],
        status=JobStatus(row["status"]),
        file_path=row["file_path"],
        cups_job_id=row["cups_job_id"],
        attempt_count=row["attempt_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_message=row["error_message"],
        metadata_json=row["metadata_json"],
    )
