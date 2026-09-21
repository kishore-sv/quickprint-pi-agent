"""Map CUPS/IPP signals to normalized printer states."""

from __future__ import annotations

import re

from app.printer_telemetry.types import (
    AdapterProbeResult,
    ConnectionState,
    DisplayState,
    OperationalState,
    PrinterCapabilities,
    PrinterTelemetrySnapshot,
)

_REASON_TO_OPERATIONAL: list[tuple[str, OperationalState]] = [
    ("media-tray-empty-error", OperationalState.PAPER_OUT),
    ("media-needed-error", OperationalState.PAPER_OUT),
    ("media-jam-error", OperationalState.PAPER_JAM),
    ("toner-low-warning", OperationalState.TONER_LOW),
    ("toner-empty-error", OperationalState.TONER_OUT),
    ("cover-open-error", OperationalState.COVER_OPEN),
    ("door-open-error", OperationalState.COVER_OPEN),
    ("paused", OperationalState.PAUSED),
    ("shutdown", OperationalState.DISABLED),
    ("stopped-partly", OperationalState.PAUSED),
    ("moving-to-paused", OperationalState.PAUSED),
]

_OFFLINE_REASON_MARKERS = (
    "device-offline",
    "offline-report",
    "connecting-to-device",
    "unreachable",
    "service-unavailable",
    "device-unreachable",
)


def parse_reason_tokens(raw: str) -> list[str]:
    if not raw or raw.strip().lower() in ("none", "null", ""):
        return []
    parts = re.split(r"[,;\s]+", raw.strip())
    return [p.strip() for p in parts if p.strip() and p.strip().lower() != "none"]


def operational_from_reasons(raw_reasons: list[str]) -> OperationalState | None:
    lowered = [r.lower() for r in raw_reasons]
    for token in lowered:
        for marker, op in _REASON_TO_OPERATIONAL:
            if marker in token:
                return op
    for token in lowered:
        if "error" in token or "warning" in token:
            if any(m in token for m in _OFFLINE_REASON_MARKERS):
                continue
            return OperationalState.ERROR
    for token in lowered:
        if any(m in token for m in _OFFLINE_REASON_MARKERS):
            return None
    return None


def connection_type_from_device_uri(device_uri: str | None) -> str:
    if not device_uri:
        return "unknown"
    lower = device_uri.lower()
    if lower.startswith("usb://") or "/usb/" in lower:
        return "usb"
    if lower.startswith("ipp://") or lower.startswith("ipps://"):
        return "ipp"
    if lower.startswith("socket://") or lower.startswith("dnssd://"):
        return "network"
    if lower.startswith("hp:/") or lower.startswith("hplip"):
        return "usb"
    return "unknown"


def split_make_and_model(make_and_model: str | None) -> tuple[str | None, str | None]:
    if not make_and_model or not make_and_model.strip():
        return None, None
    text = make_and_model.strip()
    if " " in text:
        manufacturer, model = text.split(" ", 1)
        return manufacturer.strip() or None, model.strip() or None
    return text, None


def has_connectivity_evidence(probe: AdapterProbeResult) -> bool:
    if probe.physical_usb_present is True:
        return True
    if probe.ipp_printer_state == 4:
        return True
    if probe.cups_printing:
        return True
    if probe.raw_reasons:
        return True
    if probe.backend_unreachable:
        return False
    return False


def build_capabilities(probe: AdapterProbeResult) -> PrinterCapabilities:
    manufacturer, model = split_make_and_model(probe.make_and_model)
    has_reasons = bool(probe.raw_reasons)
    has_supply = any(
        "toner" in r.lower() or "media" in r.lower() for r in probe.raw_reasons
    )
    return PrinterCapabilities(
        manufacturer=manufacturer,
        model=model,
        connection_type=connection_type_from_device_uri(probe.device_uri),
        supports_printer_state_reasons=has_reasons,
        supports_supply_information=has_supply,
    )


def derive_display_state(
    connection: ConnectionState, operational: OperationalState
) -> DisplayState:
    if connection == ConnectionState.OFFLINE:
        return DisplayState.OFFLINE
    if operational == OperationalState.PRINTING:
        return DisplayState.PRINTING
    if operational == OperationalState.IDLE and connection == ConnectionState.ONLINE:
        return DisplayState.READY
    mapping = {
        OperationalState.ERROR: DisplayState.ERROR,
        OperationalState.PAPER_OUT: DisplayState.PAPER_OUT,
        OperationalState.PAPER_JAM: DisplayState.PAPER_JAM,
        OperationalState.TONER_LOW: DisplayState.TONER_LOW,
        OperationalState.TONER_OUT: DisplayState.TONER_OUT,
        OperationalState.COVER_OPEN: DisplayState.COVER_OPEN,
        OperationalState.PAUSED: DisplayState.PAUSED,
        OperationalState.DISABLED: DisplayState.DISABLED,
        OperationalState.UNKNOWN: DisplayState.UNKNOWN,
    }
    if operational in mapping:
        return mapping[operational]
    if connection == ConnectionState.UNKNOWN:
        return DisplayState.UNKNOWN
    return DisplayState.UNKNOWN


def normalize_probe(
    probe: AdapterProbeResult,
    *,
    printer_name: str,
    last_probe_at: str,
    active_job_id: str | None,
    job_printing_hint: bool,
) -> PrinterTelemetrySnapshot:
    raw_reasons = list(probe.raw_reasons)
    reasons_normalized: list[str] = []

    if not probe.scheduler_running or not probe.queue_exists:
        connection = ConnectionState.UNKNOWN
        operational = OperationalState.UNKNOWN
    elif probe.backend_unreachable:
        connection = ConnectionState.OFFLINE
        operational = OperationalState.UNKNOWN
    elif probe.physical_usb_present is False:
        connection = ConnectionState.OFFLINE
        operational = OperationalState.UNKNOWN
    elif any(m in r.lower() for r in raw_reasons for m in _OFFLINE_REASON_MARKERS):
        connection = ConnectionState.OFFLINE
        operational = operational_from_reasons(raw_reasons) or OperationalState.UNKNOWN
    elif has_connectivity_evidence(probe):
        connection = ConnectionState.ONLINE
        operational = OperationalState.IDLE
    else:
        connection = ConnectionState.UNKNOWN
        operational = OperationalState.UNKNOWN

    if probe.ipp_printer_state == 5 or not probe.enabled:
        if connection == ConnectionState.ONLINE:
            operational = OperationalState.DISABLED
    elif probe.ipp_printer_state == 4 or probe.cups_printing or job_printing_hint:
        if connection in (ConnectionState.ONLINE, ConnectionState.UNKNOWN):
            if connection == ConnectionState.ONLINE:
                operational = OperationalState.PRINTING
    elif connection == ConnectionState.ONLINE:
        from_reasons = operational_from_reasons(raw_reasons)
        if from_reasons is not None:
            operational = from_reasons

    if not probe.accepting_jobs and connection == ConnectionState.ONLINE:
        if operational == OperationalState.IDLE:
            operational = OperationalState.PAUSED

    for r in raw_reasons:
        op = operational_from_reasons([r])
        if op is not None:
            label = op.value
            if label not in reasons_normalized:
                reasons_normalized.append(label)

    display = derive_display_state(connection, operational)
    capabilities = build_capabilities(probe)

    return PrinterTelemetrySnapshot(
        printer_name=printer_name,
        connection_state=connection,
        operational_state=operational,
        display_state=display,
        reasons=reasons_normalized,
        raw_reasons=raw_reasons,
        last_probe_at=last_probe_at,
        capabilities=capabilities,
        active_job_id=active_job_id,
    )


def unknown_snapshot(printer_name: str, last_probe_at: str) -> PrinterTelemetrySnapshot:
    return PrinterTelemetrySnapshot(
        printer_name=printer_name,
        connection_state=ConnectionState.UNKNOWN,
        operational_state=OperationalState.UNKNOWN,
        display_state=DisplayState.UNKNOWN,
        reasons=[],
        raw_reasons=[],
        last_probe_at=last_probe_at,
        capabilities=PrinterCapabilities(),
    )
