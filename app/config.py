"""Environment-based configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _load_dotenv() -> None:
    """Load .env from project root if present (simple KEY=VALUE parser)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    agent_env: str
    agent_id: str
    agent_secret: str
    backend_url: str
    backend_ws_url: str
    job_directory: Path
    database_path: Path
    printer_mode: str
    cups_printer_name: str
    log_level: str
    max_download_bytes: int
    mock_print_delay_seconds: float
    mock_print_failure: bool
    download_timeout_seconds: int
    heartbeat_interval_seconds: int
    ws_reconnect_max_delay_seconds: int

    @property
    def is_development(self) -> bool:
        return self.agent_env.lower() == "development"

    @property
    def incoming_dir(self) -> Path:
        return self.job_directory / "incoming"

    @property
    def processing_dir(self) -> Path:
        return self.job_directory / "processing"

    @property
    def completed_dir(self) -> Path:
        return self.job_directory / "completed"

    @property
    def failed_dir(self) -> Path:
        return self.job_directory / "failed"


def load_settings() -> Settings:
    _load_dotenv()

    agent_env = os.environ.get("AGENT_ENV", "development").strip().lower()
    agent_id = os.environ.get("AGENT_ID", "").strip()
    agent_secret = os.environ.get("AGENT_SECRET", "").strip()
    backend_url = os.environ.get("BACKEND_URL", "").strip()
    backend_ws_url = os.environ.get("BACKEND_WS_URL", "").strip()

    job_directory = Path(
        os.environ.get("JOB_DIRECTORY", "jobs").strip() or "jobs"
    )
    if not job_directory.is_absolute():
        job_directory = PROJECT_ROOT / job_directory

    database_path = Path(
        os.environ.get("DATABASE_PATH", "data/agent.db").strip() or "data/agent.db"
    )
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    printer_mode = os.environ.get("PRINTER_MODE", "mock").strip().lower()
    cups_printer_name = os.environ.get("CUPS_PRINTER_NAME", "").strip()
    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

    settings = Settings(
        agent_env=agent_env,
        agent_id=agent_id,
        agent_secret=agent_secret,
        backend_url=backend_url,
        backend_ws_url=backend_ws_url,
        job_directory=job_directory,
        database_path=database_path,
        printer_mode=printer_mode,
        cups_printer_name=cups_printer_name,
        log_level=log_level,
        max_download_bytes=_env_int("MAX_DOWNLOAD_BYTES", 52_428_800),
        mock_print_delay_seconds=_env_float("MOCK_PRINT_DELAY_SECONDS", 0.1),
        mock_print_failure=_env_bool("MOCK_PRINT_FAILURE", False),
        download_timeout_seconds=_env_int("DOWNLOAD_TIMEOUT_SECONDS", 120),
        heartbeat_interval_seconds=_env_int("HEARTBEAT_INTERVAL_SECONDS", 30),
        ws_reconnect_max_delay_seconds=_env_int("WS_RECONNECT_MAX_DELAY_SECONDS", 60),
    )

    _validate_settings(settings)
    return settings


def _validate_settings(settings: Settings) -> None:
    if settings.printer_mode not in ("mock", "cups"):
        raise ConfigurationError(
            f"PRINTER_MODE must be 'mock' or 'cups', got '{settings.printer_mode}'"
        )

    if settings.printer_mode == "cups" and not settings.cups_printer_name:
        raise ConfigurationError(
            "CUPS_PRINTER_NAME is required when PRINTER_MODE=cups"
        )

    if settings.is_development:
        return

    missing: list[str] = []
    if not settings.agent_id:
        missing.append("AGENT_ID")
    if not settings.agent_secret:
        missing.append("AGENT_SECRET")
    if not settings.backend_ws_url:
        missing.append("BACKEND_WS_URL")
    if missing:
        raise ConfigurationError(
            f"Production configuration missing required values: {', '.join(missing)}"
        )


def ensure_runtime_directories(settings: Settings) -> None:
    settings.job_directory.mkdir(parents=True, exist_ok=True)
    settings.incoming_dir.mkdir(parents=True, exist_ok=True)
    settings.processing_dir.mkdir(parents=True, exist_ok=True)
    settings.completed_dir.mkdir(parents=True, exist_ok=True)
    settings.failed_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
