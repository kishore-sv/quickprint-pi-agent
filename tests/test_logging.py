"""Logging redaction tests."""

import logging

from app.logger import SecretRedactionFilter, redact_url, redact_url_in_text, setup_logging


def test_redact_url_strips_query():
    url = "https://storage.example.com/file.pdf?token=secret&sig=abc"
    assert redact_url(url) == "https://storage.example.com/file.pdf"


def test_redact_url_in_text():
    text = "fetch https://x.com/a.pdf?token=secret now"
    assert "token=" not in redact_url_in_text(text)


def test_secret_redaction_filter():
    setup_logging("INFO")
    logger = logging.getLogger("test.redaction")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Authorization: Bearer abc:secret123",
        args=(),
        exc_info=None,
    )
    filt = SecretRedactionFilter()
    filt.filter(record)
    assert "secret123" not in record.msg
