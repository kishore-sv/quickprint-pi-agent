"""Generic CUPS-first printer telemetry."""

from app.printer_telemetry.service import PrinterTelemetryService
from app.printer_telemetry.types import PrinterTelemetrySnapshot

__all__ = ["PrinterTelemetryService", "PrinterTelemetrySnapshot"]
