"""Normalized printer telemetry types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConnectionState(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


class OperationalState(str, Enum):
    IDLE = "IDLE"
    PRINTING = "PRINTING"
    ERROR = "ERROR"
    PAPER_OUT = "PAPER_OUT"
    PAPER_JAM = "PAPER_JAM"
    TONER_LOW = "TONER_LOW"
    TONER_OUT = "TONER_OUT"
    COVER_OPEN = "COVER_OPEN"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


class DisplayState(str, Enum):
    READY = "READY"
    PRINTING = "PRINTING"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    PAPER_OUT = "PAPER_OUT"
    PAPER_JAM = "PAPER_JAM"
    TONER_LOW = "TONER_LOW"
    TONER_OUT = "TONER_OUT"
    COVER_OPEN = "COVER_OPEN"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PrinterCapabilities:
    manufacturer: str | None = None
    model: str | None = None
    connection_type: str = "unknown"
    supports_printer_state_reasons: bool = False
    supports_supply_information: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "manufacturer": self.manufacturer,
            "model": self.model,
            "connection_type": self.connection_type,
            "supports_printer_state_reasons": self.supports_printer_state_reasons,
            "supports_supply_information": self.supports_supply_information,
        }


@dataclass
class AdapterProbeResult:
    """Raw signals from a single adapter layer."""

    queue_exists: bool = False
    scheduler_running: bool = False
    enabled: bool = True
    accepting_jobs: bool = True
    cups_idle: bool = False
    cups_printing: bool = False
    ipp_printer_state: int | None = None  # 3 idle, 4 processing, 5 stopped
    raw_reasons: list[str] = field(default_factory=list)
    state_message: str | None = None
    device_uri: str | None = None
    make_and_model: str | None = None
    physical_usb_present: bool | None = None  # HPLIP hint
    backend_unreachable: bool = False


@dataclass
class PrinterTelemetrySnapshot:
    printer_name: str
    connection_state: ConnectionState
    operational_state: OperationalState
    display_state: DisplayState
    reasons: list[str]
    raw_reasons: list[str]
    last_probe_at: str
    capabilities: PrinterCapabilities
    active_job_id: str | None = None

    def state_key(self) -> tuple:
        """Fields that constitute a meaningful state change (excludes heartbeat-only)."""
        return (
            self.connection_state,
            self.operational_state,
            self.display_state,
            tuple(self.reasons),
            tuple(self.raw_reasons),
            self.capabilities.manufacturer,
            self.capabilities.model,
            self.capabilities.connection_type,
        )

    def to_wire_dict(
        self,
        *,
        agent_id: str,
        event_id: str,
        sequence: int,
        timestamp: str,
        is_heartbeat: bool,
    ) -> dict[str, Any]:
        return {
            "type": "printer.telemetry",
            "agent_id": agent_id,
            "event_id": event_id,
            "sequence": sequence,
            "timestamp": timestamp,
            "printer_name": self.printer_name,
            "connection_state": self.connection_state.value,
            "operational_state": self.operational_state.value,
            "display_state": self.display_state.value,
            "reasons": list(self.reasons),
            "raw_reasons": list(self.raw_reasons),
            "last_probe_at": self.last_probe_at,
            "capabilities": self.capabilities.to_dict(),
            "is_heartbeat": is_heartbeat,
            "active_job_id": self.active_job_id,
        }
