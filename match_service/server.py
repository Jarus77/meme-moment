"""Thin HTTP wrapper around MatchApp (standard library only)."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .app import MAX_BODY_BYTES, MatchApp


def make_server(app: MatchApp, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _dispatch(self, method: str) -> None:
            try:
                length = max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                return self._respond(400, {"error": "bad Content-Length"})
            body = self.rfile.read(min(length, MAX_BODY_BYTES + 1)) if length else b""
            status, payload = app.handle(method, self.path.split("?")[0], dict(self.headers), body)
            self._respond(status, payload)

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def log_message(self, format: str, *args) -> None:  # request lines only, never bodies
            super().log_message(format, *args)

    return ThreadingHTTPServer((host, port), Handler)
