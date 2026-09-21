"""Environment-based configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""


def _env(name: str, fallback: str = "") -> str:
    return os.environ.get(name, fallback).strip()


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        val = os.environ.get(name)
        if val is not None and val.strip():
            return val.strip()
    return default


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


def physical_completion_stable_seconds_from_env(
    default: float = 5.0,
) -> float:
    """PHYSICAL_COMPLETION_STABLE_SECONDS — quiescence after CUPS job COMPLETED (P1106 mitigation)."""
    raw = os.environ.get("PHYSICAL_COMPLETION_STABLE_SECONDS")
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    if value < 0:
        return default
    return value


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
    cups_server: str
    log_level: str
    health_refresh_interval_seconds: float
    max_download_bytes: int
    mock_print_delay_seconds: float
    mock_print_failure: bool
    download_timeout_seconds: int
    heartbeat_interval_seconds: int
    ws_reconnect_max_delay_seconds: int
    retry_max_attempts: int
    retry_base_delay_seconds: float
    retry_max_delay_seconds: float
    cups_command_timeout_seconds: float
    job_poll_interval_seconds: float
    printer_telemetry_enabled: bool
    printer_telemetry_interval_seconds: float
    printer_telemetry_heartbeat_seconds: float
    printer_hplip_fallback_enabled: bool
    physical_completion_stable_seconds: float = 5.0

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

    agent_env = _env_first("AGENT_ENV", "ENVIRONMENT", default="development").lower()
    agent_id = _env("AGENT_ID")
    agent_secret = _env_first("AGENT_SECRET", "AGENT_TOKEN")
    backend_url = _env_first("BACKEND_URL", "BACKEND_API_URL")
    backend_ws_url = _env("BACKEND_WS_URL")

    job_directory = Path(_env("JOB_DIRECTORY", "jobs") or "jobs")
    if not job_directory.is_absolute():
        job_directory = PROJECT_ROOT / job_directory

    database_path = Path(_env("DATABASE_PATH", "data/agent.db") or "data/agent.db")
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    printer_mode = _env("PRINTER_MODE", "mock").lower()
    # Canonical: CUPS_PRINTER_NAME. Legacy fallbacks (first non-empty wins): PRINTER_NAME, CUPS_PRINTER.
    cups_printer_name = _env_first("CUPS_PRINTER_NAME", "PRINTER_NAME", "CUPS_PRINTER")
    cups_server = _env("CUPS_SERVER")
    log_level = _env("LOG_LEVEL", "INFO").upper()

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
        cups_server=cups_server,
        log_level=log_level,
        health_refresh_interval_seconds=_env_float(
            "HEALTH_REFRESH_INTERVAL_SECONDS", 60.0
        ),
        max_download_bytes=_env_int("MAX_DOWNLOAD_BYTES", _env_int("DOWNLOAD_MAX_BYTES", 52_428_800)),
        mock_print_delay_seconds=_env_float("MOCK_PRINT_DELAY_SECONDS", 0.1),
        mock_print_failure=_env_bool("MOCK_PRINT_FAILURE", False),
        download_timeout_seconds=_env_int("DOWNLOAD_TIMEOUT_SECONDS", 120),
        heartbeat_interval_seconds=_env_int("HEARTBEAT_INTERVAL_SECONDS", 30),
        ws_reconnect_max_delay_seconds=_env_int("WS_RECONNECT_MAX_DELAY_SECONDS", 60),
        retry_max_attempts=_env_int("RETRY_MAX_ATTEMPTS", 3),
        retry_base_delay_seconds=_env_float("RETRY_BASE_DELAY_SECONDS", 1.0),
        retry_max_delay_seconds=_env_float("RETRY_MAX_DELAY_SECONDS", 30.0),
        cups_command_timeout_seconds=_env_float("CUPS_COMMAND_TIMEOUT_SECONDS", 30.0),
        job_poll_interval_seconds=_env_float("JOB_POLL_INTERVAL_SECONDS", 1.0),
        printer_telemetry_enabled=_env_bool(
            "PRINTER_TELEMETRY_ENABLED",
            _env("PRINTER_MODE", "mock").lower() == "cups",
        ),
        printer_telemetry_interval_seconds=_env_float(
            "PRINTER_TELEMETRY_INTERVAL_SECONDS", 3.0
        ),
        printer_telemetry_heartbeat_seconds=_env_float(
            "PRINTER_TELEMETRY_HEARTBEAT_SECONDS", 10.0
        ),
        printer_hplip_fallback_enabled=_env_bool(
            "PRINTER_HPLIP_FALLBACK_ENABLED", True
        ),
        physical_completion_stable_seconds=physical_completion_stable_seconds_from_env(
            5.0
        ),
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
            "CUPS_PRINTER_NAME is required when PRINTER_MODE=cups "
            "(legacy fallbacks: PRINTER_NAME, CUPS_PRINTER — only used if CUPS_PRINTER_NAME is unset)"
        )

    if settings.is_development:
        return

    missing: list[str] = []
    if not settings.agent_id:
        missing.append("AGENT_ID")
    if not settings.agent_secret:
        missing.append("AGENT_SECRET/AGENT_TOKEN")
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
