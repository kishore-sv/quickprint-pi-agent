"""PHYSICAL_COMPLETION_STABLE_SECONDS configuration."""

from __future__ import annotations

import pytest

from app.config import physical_completion_stable_seconds_from_env


def test_missing_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHYSICAL_COMPLETION_STABLE_SECONDS", raising=False)
    assert physical_completion_stable_seconds_from_env() == 5.0


def test_custom_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHYSICAL_COMPLETION_STABLE_SECONDS", "8")
    assert physical_completion_stable_seconds_from_env() == 8.0


def test_invalid_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHYSICAL_COMPLETION_STABLE_SECONDS", "not-a-number")
    assert physical_completion_stable_seconds_from_env() == 5.0


def test_negative_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHYSICAL_COMPLETION_STABLE_SECONDS", "-1")
    assert physical_completion_stable_seconds_from_env() == 5.0
