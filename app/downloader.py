"""Stream file downloads from signed URLs."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.logger import get_logger, redact_url

log = get_logger("downloader")

_UNSAFE_NAME = re.compile(r"[^\w.\-]+")


class DownloadError(Exception):
    """Download failed."""


class RetryableDownloadError(DownloadError):
    """Transient download failure."""


class PermanentDownloadError(DownloadError):
    """Non-retryable download failure."""


def sanitize_filename(name: str | None, fallback: str = "job.pdf") -> str:
    if not name or not name.strip():
        return fallback
    if ".." in name or "/" in name or "\\" in name:
        return fallback
    base = Path(name).name
    if base in (".", ".."):
        return fallback
    safe = _UNSAFE_NAME.sub("_", base).strip("._")
    if not safe:
        return fallback
    return safe[:200]


def _download_sync(
    url: str,
    dest_part: Path,
    max_bytes: int,
    timeout_seconds: int,
) -> None:
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            if resp.status and resp.status >= 400:
                if resp.status >= 500:
                    raise RetryableDownloadError(f"HTTP {resp.status}")
                raise PermanentDownloadError(f"HTTP {resp.status}")
            content_length = resp.headers.get("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) > max_bytes:
                        raise PermanentDownloadError(
                            f"File exceeds maximum size ({max_bytes} bytes)"
                        )
                except ValueError:
                    pass
            dest_part.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            with open(dest_part, "wb") as out:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        out.close()
                        dest_part.unlink(missing_ok=True)
                        raise PermanentDownloadError(
                            f"Download exceeded maximum size ({max_bytes} bytes)"
                        )
                    out.write(chunk)
    except HTTPError as e:
        if e.code >= 500:
            raise RetryableDownloadError(f"HTTP error {e.code}") from e
        raise PermanentDownloadError(f"HTTP error {e.code}") from e
    except URLError as e:
        raise RetryableDownloadError(f"URL error: {e.reason}") from e


class Downloader:
    def __init__(
        self,
        incoming_dir: Path,
        max_bytes: int,
        timeout_seconds: int,
    ) -> None:
        self._incoming_dir = incoming_dir
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds

    async def download(
        self,
        url: str,
        backend_job_id: str,
        filename_hint: str | None,
    ) -> Path:
        safe_name = sanitize_filename(filename_hint)
        final_name = f"{backend_job_id}_{safe_name}"
        part_path = self._incoming_dir / f"{final_name}.part"
        final_path = self._incoming_dir / final_name

        log.info(
            "Downloading file from %s %s",
            redact_url(url),
            f"job_id={backend_job_id}",
        )

        try:
            await asyncio.to_thread(
                _download_sync,
                url,
                part_path,
                self._max_bytes,
                self._timeout_seconds,
            )
        except DownloadError as e:
            log.error("Download failed job_id=%s reason=%s", backend_job_id, e)
            raise

        os.replace(part_path, final_path)
        return final_path
