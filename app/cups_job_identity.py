"""Deterministic CUPS job titles for duplicate-print recovery."""

from __future__ import annotations

import re

_TITLE_PREFIX = "QuickPrint:"
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_backend_job_id_for_cups(backend_job_id: str) -> str:
    if not backend_job_id or not isinstance(backend_job_id, str):
        raise ValueError("backend_job_id must be a non-empty string")
    safe = _SAFE_ID.sub("", backend_job_id.strip())
    if not safe:
        raise ValueError("backend_job_id contains no safe characters for CUPS title")
    return safe[:120]


def cups_job_title(backend_job_id: str) -> str:
    return f"{_TITLE_PREFIX}{sanitize_backend_job_id_for_cups(backend_job_id)}"


def extract_titles_from_lpstat_long(text: str) -> list[str]:
    titles: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("title:"):
            title = stripped.split(":", 1)[1].strip()
            if title:
                titles.append(title)
    return titles


def lpstat_text_contains_exact_title(text: str, marker: str) -> bool:
    return marker in extract_titles_from_lpstat_long(text)
