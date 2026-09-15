#!/usr/bin/env python3
"""Local bootstrap HTTP server for QuickPrint kiosk display pairing.

Binds only to 127.0.0.1:18765. Serves a one-shot bootstrap page that POSTs to the
backend display-session endpoint with credentials so the httpOnly cookie is set on
the API host. DISPLAY_TOKEN is never written to disk; it is injected per request
only into the ephemeral bootstrap response served to localhost.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 18765


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required", 1)
    return value


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

    def do_GET(self) -> None:
        if self.path not in ("/", "/pair"):
            self.send_error(404, "Not found")
            return

        session_url = (
            f"{self.api_url.rstrip('/')}/kiosks/{self.kiosk_code}/display-session"
        )
        body = (
            "<!DOCTYPE html><html lang=\"en\"><head>"
            "<meta charset=\"utf-8\"><title>QuickPrint Display</title></head><body>"
            "<p>Pairing kiosk display&hellip;</p><script>"
            "(async function () {"
            f"  const sessionUrl = {json.dumps(session_url)};"
            f"  const displayUrl = {json.dumps(self.display_url)};"
            f"  const auth = {json.dumps(f'Bearer {self.kiosk_code}:{self.display_token}')};"
            "  try {"
            "    const res = await fetch(sessionUrl, {"
            "      method: 'POST',"
            "      headers: { Authorization: auth },"
            "      credentials: 'include',"
            "    });"
            "    if (!res.ok) throw new Error('pairing failed');"
            "    location.replace(displayUrl);"
            "  } catch (e) {"
            "    document.body.textContent = 'Display pairing failed. Check API_URL and DISPLAY_TOKEN.';"
            "  }"
            "})();"
            "</script></body></html>"
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
