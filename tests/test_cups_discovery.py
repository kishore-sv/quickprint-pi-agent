"""CUPS lpstat parsing tests."""

from app.cups_discovery import parse_lpstat_printer_status


def test_parse_idle_accepting():
    parsed = parse_lpstat_printer_status(
        "printer quickprint-test is idle, accepting jobs since Mon 01 Jan 2024"
    )
    assert parsed["exists"] is True
    assert parsed["enabled"] is True
    assert parsed["accepting_jobs"] is True
    assert parsed["idle"] is True


def test_parse_disabled():
    parsed = parse_lpstat_printer_status(
        "printer quickprint-test disabled since Mon 01 Jan 2024"
    )
    assert parsed["enabled"] is False


def test_parse_not_accepting():
    parsed = parse_lpstat_printer_status(
        "printer quickprint-test is idle, not accepting jobs since Mon 01 Jan 2024"
    )
    assert parsed["accepting_jobs"] is False


def test_parse_printing():
    parsed = parse_lpstat_printer_status(
        "printer quickprint-test is printing since Mon 01 Jan 2024"
    )
    assert parsed["printing"] is True
