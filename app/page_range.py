"""Safe validation for CUPS page-ranges values."""

from __future__ import annotations

import re

_ALLOWED = re.compile(r"^[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*$")


def validate_page_range(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if not _ALLOWED.match(stripped):
        raise ValueError(f"Invalid page range: {value}")
    for segment in stripped.split(","):
        if "-" in segment:
            start_s, end_s = segment.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start < 1 or end < 1 or start > end:
                raise ValueError(f"Invalid page range segment: {segment}")
        else:
            if int(segment) < 1:
                raise ValueError(f"Invalid page range segment: {segment}")
    return stripped
