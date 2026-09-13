import pytest

from app.page_range import validate_page_range


def test_valid_ranges():
    assert validate_page_range("1") == "1"
    assert validate_page_range("1-5") == "1-5"
    assert validate_page_range("1,3,5") == "1,3,5"
    assert validate_page_range("1-3,7-9") == "1-3,7-9"
    assert validate_page_range(None) is None


def test_invalid_ranges():
    with pytest.raises(ValueError):
        validate_page_range("1-")
    with pytest.raises(ValueError):
        validate_page_range("a-b")
    with pytest.raises(ValueError):
        validate_page_range("5-1")
