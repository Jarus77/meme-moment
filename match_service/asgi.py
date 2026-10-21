"""ASGI adapter so the service can run on any standard host (Modal, Vercel Python, uvicorn, ...)."""
from __future__ import annotations

import asyncio
import json

from .app import MAX_BODY_BYTES, MatchApp


def make_asgi_app(app: MatchApp):
    async def lifespan(receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def read_body(receive) -> bytes | None:
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            body += message.get("body", b"")
            if len(body) > MAX_BODY_BYTES:  # stop buffering; MatchApp answers 413
                return body[: MAX_BODY_BYTES + 1]
            if not message.get("more_body"):
                return body

    async def asgi(scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            return await lifespan(receive, send)
        if scope["type"] != "http":
            return
        body = await read_body(receive)
        if body is None:
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        # The encoder runs for seconds on CPU; keep the event loop free.
        status, payload = await asyncio.to_thread(app.handle, scope["method"], scope["path"], headers, body)
        data = json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(data)).encode()),
            (b"cache-control", b"no-store"),
        ]})
        await send({"type": "http.response.body", "body": data})

    return asgi
