"""Tests for printer telemetry normalization."""

from app.printer_telemetry.normalize import (
    derive_display_state,
    normalize_probe,
    operational_from_reasons,
    parse_reason_tokens,
)
from app.printer_telemetry.types import (
    AdapterProbeResult,
    ConnectionState,
    DisplayState,
    OperationalState,
)


def test_parse_reason_tokens_none():
    assert parse_reason_tokens("none") == []
    assert parse_reason_tokens("media-jam-error, none") == ["media-jam-error"]


def test_operational_from_media_tray_empty():
    assert operational_from_reasons(["media-tray-empty-error"]) == OperationalState.PAPER_OUT


def test_operational_from_toner_low():
    assert operational_from_reasons(["toner-low-warning"]) == OperationalState.TONER_LOW


def test_cups_idle_without_connectivity_is_unknown():
    probe = AdapterProbeResult(
        queue_exists=True,
        scheduler_running=True,
        cups_idle=True,
        enabled=True,
        accepting_jobs=True,
    )
    snap = normalize_probe(
        probe,
        printer_name="p1",
        last_probe_at="2026-01-01T00:00:00Z",
        active_job_id=None,
        job_printing_hint=False,
    )
    assert snap.connection_state == ConnectionState.UNKNOWN
    assert snap.display_state == DisplayState.UNKNOWN


def test_hplip_usb_present_yields_ready_when_idle():
    probe = AdapterProbeResult(
        queue_exists=True,
        scheduler_running=True,
        cups_idle=True,
        physical_usb_present=True,
        device_uri="usb://HP",
    )
    snap = normalize_probe(
        probe,
        printer_name="p1",
        last_probe_at="2026-01-01T00:00:00Z",
        active_job_id=None,
        job_printing_hint=False,
    )
    assert snap.connection_state == ConnectionState.ONLINE
    assert snap.display_state == DisplayState.READY


def test_processing_state_printing():
    probe = AdapterProbeResult(
        queue_exists=True,
        scheduler_running=True,
        ipp_printer_state=4,
        physical_usb_present=True,
    )
    snap = normalize_probe(
        probe,
        printer_name="p1",
        last_probe_at="2026-01-01T00:00:00Z",
        active_job_id="job-1",
        job_printing_hint=True,
    )
    assert snap.operational_state == OperationalState.PRINTING
    assert snap.display_state == DisplayState.PRINTING


def test_media_jam_error():
    probe = AdapterProbeResult(
        queue_exists=True,
        scheduler_running=True,
        raw_reasons=["media-jam-error"],
        physical_usb_present=True,
    )
    snap = normalize_probe(
        probe,
        printer_name="p1",
        last_probe_at="2026-01-01T00:00:00Z",
        active_job_id=None,
        job_printing_hint=False,
    )
    assert snap.operational_state == OperationalState.PAPER_JAM
    assert snap.display_state == DisplayState.PAPER_JAM


def test_hp_probe_offline():
    probe = AdapterProbeResult(
        queue_exists=True,
        scheduler_running=True,
        cups_idle=True,
        physical_usb_present=False,
        device_uri="hp:/usb/...",
    )
    snap = normalize_probe(
        probe,
        printer_name="p1",
        last_probe_at="2026-01-01T00:00:00Z",
        active_job_id=None,
        job_printing_hint=False,
    )
    assert snap.connection_state == ConnectionState.OFFLINE
    assert snap.display_state == DisplayState.OFFLINE


def test_derive_display_offline():
    assert (
        derive_display_state(ConnectionState.OFFLINE, OperationalState.UNKNOWN)
        == DisplayState.OFFLINE
    )
