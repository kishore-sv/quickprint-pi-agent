"""CUPS job state parsing (no false 'completed' from spooler phrases)."""

from app.cups_job_state import parse_lpstat_long_job, parse_lpstat_short_job_line
from app.printer import PrinterJobState


def test_rendering_completed_is_still_printing():
    assert (
        parse_lpstat_short_job_line(
            "quickprint-printer-64 user 1283072 Rendering completed"
        )
        == PrinterJobState.PRINTING
    )


def test_spooling_completed_is_still_printing():
    assert (
        parse_lpstat_short_job_line("P-1 user 1024 Spooling completed")
        == PrinterJobState.PRINTING
    )


def test_terminal_completed_token():
    assert (
        parse_lpstat_short_job_line("quickprint-printer-64 user 1024 completed")
        == PrinterJobState.COMPLETED
    )


def test_processing_token():
    assert (
        parse_lpstat_short_job_line("quickprint-printer-64 user 1024 processing")
        == PrinterJobState.PRINTING
    )


def test_lpstat_long_job_state_completed():
    state, reasons = parse_lpstat_long_job(
        "job-state: Completed\njob-state-reasons: job-completed-successfully\n"
    )
    assert state == PrinterJobState.COMPLETED
    assert "job-completed-successfully" in reasons


def test_lpstat_long_job_state_processing():
    state, _ = parse_lpstat_long_job("job-state: Processing\n")
    assert state == PrinterJobState.PRINTING
