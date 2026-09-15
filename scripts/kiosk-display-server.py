#!/usr/bin/env python3
"""Local bootstrap HTTP server for QuickPrint kiosk display pairing.

Binds only to 127.0.0.1:18765. Serves an ephemeral HTML form that performs a
top-level POST to the backend display-session endpoint. Top-level navigation is
required so Chromium stores the HttpOnly qp_kiosk_display cookie (fetch() from a
cross-origin bootstrap page cannot set SameSite=Lax cookies).

DISPLAY_TOKEN is never written to disk and never exposed over the LAN; it exists
only in the ephemeral localhost HTML form body.
"""

from __future__ import annotations

import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 18765

ERROR_MESSAGES = {
    "pairing_failed": "Display pairing failed: invalid display token or kiosk code.",
    "invalid_redirect": "Display pairing failed: display URL is not allowed.",
    "unknown": "Display pairing failed: unexpected error.",
}


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required", 1)
    return value


def _html_page(title: str, body: str) -> bytes:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head>"
        f"<meta charset=\"utf-8\"><title>{html.escape(title)}</title>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;line-height:1.5;}"
        ".err{color:#b00020;}"
        "</style></head><body>"
        f"{body}</body></html>"
    ).encode("utf-8")


class BootstrapHandler(BaseHTTPRequestHandler):
    api_url = ""
    display_url = ""
    kiosk_code = ""
    display_token = ""

    def log_message(self, format: str, *args) -> None:
        message = format % args
        if self.display_token and self.display_token in message:
            message = message.replace(self.display_token, "<redacted>")
        sys.stderr.write(f"[kiosk-display-bootstrap] {message}\n")

    def _send_html(self, status: int, title: str, body: str) -> None:
        payload = _html_page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            payload = json.dumps({"ok": True, "bootstrap": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/error":
            code = parse_qs(parsed.query).get("code", ["unknown"])[0]
            message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["unknown"])
            self._send_html(
                200,
                "QuickPrint Display",
                f"<p class=\"err\">{html.escape(message)}</p>"
                "<p>Check API_URL, DISPLAY_URL, and DISPLAY_TOKEN in .env.display, "
                "then restart quickprint-display.service.</p>",
            )
            return

        if parsed.path not in ("/", "/pair"):
            self.send_error(404, "Not found")
            return

        session_url = (
            f"{self.api_url.rstrip('/')}/kiosks/{self.kiosk_code}/display-session"
        )
        body = (
            "<p>Pairing kiosk display&hellip;</p>"
            f"<form id=\"pair-form\" method=\"POST\" action=\"{html.escape(session_url, quote=True)}\">"
            f"<input type=\"hidden\" name=\"display_token\" value=\"{html.escape(self.display_token, quote=True)}\">"
            f"<input type=\"hidden\" name=\"redirect_url\" value=\"{html.escape(self.display_url, quote=True)}\">"
            "<noscript><button type=\"submit\">Continue pairing</button></noscript>"
            "</form>"
            "<script>"
            "document.getElementById('pair-form').submit();"
            "</script>"
        )
        self._send_html(200, "QuickPrint Display", body)

    def do_OPTIONS(self) -> None:
        self.send_error(405, "Method not allowed")


def main() -> None:
    api_url = _required_env("API_URL")
    display_url = _required_env("DISPLAY_URL")
    display_token = _required_env("DISPLAY_TOKEN")
    kiosk_code = os.environ.get("KIOSK_CODE", "KIOSK-001").strip() or "KIOSK-001"

    BootstrapHandler.api_url = api_url
    BootstrapHandler.display_url = display_url
    BootstrapHandler.kiosk_code = kiosk_code
    BootstrapHandler.display_token = display_token

    server = ThreadingHTTPServer((HOST, PORT), BootstrapHandler)
    if server.server_address[0] != HOST:
        raise SystemExit(f"refusing to bind outside localhost (got {server.server_address[0]})", 1)

    print(f"Bootstrap server listening on http://{HOST}:{PORT}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
