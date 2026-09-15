"""Tests for the local kiosk display bootstrap HTTP server."""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_SCRIPT = REPO_ROOT / "scripts" / "kiosk-display-server.py"


def _load_server_module():
    spec = importlib.util.spec_from_file_location("kiosk_display_server", SERVER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bootstrap_env(monkeypatch):
    monkeypatch.setenv("API_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("DISPLAY_URL", "http://127.0.0.1:3000/kiosk/KIOSK-001")
    monkeypatch.setenv("DISPLAY_TOKEN", "test-display-token-secret")
    monkeypatch.setenv("KIOSK_CODE", "KIOSK-001")


@pytest.fixture
def bootstrap_server(bootstrap_env):
    module = _load_server_module()
    server = module.ThreadingHTTPServer((module.HOST, 0), module.BootstrapHandler)
    module.BootstrapHandler.api_url = os.environ["API_URL"]
    module.BootstrapHandler.display_url = os.environ["DISPLAY_URL"]
    module.BootstrapHandler.kiosk_code = os.environ["KIOSK_CODE"]
    module.BootstrapHandler.display_token = os.environ["DISPLAY_TOKEN"]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_get_root_returns_200_no_store(bootstrap_server):
    with urllib.request.urlopen(f"{bootstrap_server}/") as response:
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert response.headers.get("Cache-Control") == "no-store"
        assert "Pairing kiosk display" in body


def test_form_posts_to_display_session_without_token_in_action_url(bootstrap_server):
    with urllib.request.urlopen(f"{bootstrap_server}/") as response:
        body = response.read().decode("utf-8")
        assert 'action="http://127.0.0.1:8000/kiosks/KIOSK-001/display-session"' in body
        assert "displayToken=" not in body
        assert "?display_token=" not in body


def test_display_token_only_in_hidden_form_field(bootstrap_server):
    with urllib.request.urlopen(f"{bootstrap_server}/") as response:
        body = response.read().decode("utf-8")
        assert 'name="display_token"' in body
        assert "test-display-token-secret" in body
        assert "redirect_url" in body
        assert "http://127.0.0.1:3000/kiosk/KIOSK-001" in body


def test_display_url_has_no_token_query(bootstrap_server):
    with urllib.request.urlopen(f"{bootstrap_server}/") as response:
        body = response.read().decode("utf-8")
        assert "kiosk/KIOSK-001" in body
        assert "displayToken=" not in body


def test_health_endpoint(bootstrap_server):
    with urllib.request.urlopen(f"{bootstrap_server}/health") as response:
        assert response.status == 200
        assert response.headers.get("Cache-Control") == "no-store"


def test_error_page_does_not_expose_token(bootstrap_server):
    with urllib.request.urlopen(f"{bootstrap_server}/error?code=pairing_failed") as response:
        body = response.read().decode("utf-8")
        assert response.status == 200
        assert "test-display-token-secret" not in body
        assert "Display pairing failed" in body


def test_server_binds_localhost_only(bootstrap_env):
    module = _load_server_module()
    server = module.ThreadingHTTPServer((module.HOST, 0), module.BootstrapHandler)
    host, _port = server.server_address
    server.server_close()
    assert host == "127.0.0.1"


def test_script_refuses_missing_env():
    env = os.environ.copy()
    env.pop("DISPLAY_TOKEN", None)
    env.setdefault("API_URL", "http://127.0.0.1:8000")
    env.setdefault("DISPLAY_URL", "http://127.0.0.1:3000/kiosk/KIOSK-001")
    result = subprocess.run(
        [sys.executable, str(SERVER_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "DISPLAY_TOKEN" in result.stderr or "DISPLAY_TOKEN" in result.stdout
