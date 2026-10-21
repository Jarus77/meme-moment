import asyncio
import json

import numpy as np
import pytest

from match_service.app import MAX_BODY_BYTES, MatchApp
from match_service.asgi import make_asgi_app
from match_service.index import TemplateIndex
from tests.test_match_app import FakeEncoder
from tests.test_match_index import template

KEY = "k"


@pytest.fixture
def asgi():
    app = MatchApp(TemplateIndex(np.array([[1, 0, 0]], dtype=np.float32), [template(1, "Alpha")]),
                   FakeEncoder(), KEY, "m")
    return make_asgi_app(app)


def run(asgi, method="GET", path="/health", headers=(), body_chunks=(b"",), query=b""):
    """Drive an ASGI app with fake receive/send; returns (status, headers dict, parsed JSON)."""
    sent: list[dict] = []
    chunks = list(body_chunks)

    async def receive():
        chunk = chunks.pop(0) if chunks else b""
        return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "query_string": query,
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers]}
    asyncio.run(asgi(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, json.loads(body)


def test_health_returns_json_with_headers(asgi):
    status, headers, body = run(asgi)
    assert status == 200 and body["ok"] is True
    assert headers["content-type"] == "application/json" and headers["cache-control"] == "no-store"
    assert int(headers["content-length"]) > 0


def test_match_with_key_and_body_split_across_chunks(asgi):
    payload = json.dumps({"description": "a man reading a book"}).encode()
    chunks = (payload[:10], payload[10:25], payload[25:])
    status, _, body = run(asgi, "POST", "/match", [("X-Match-Key", KEY)], chunks)
    assert status == 200 and body["matches"][0]["template"]["name"] == "Alpha"


def test_missing_key_is_401(asgi):
    status, _, _ = run(asgi, "POST", "/match", [], (b'{"description": "abc def"}',))
    assert status == 401


def test_query_string_does_not_change_routing(asgi):
    assert run(asgi, query=b"x=1")[0] == 200


def test_oversized_body_is_rejected_with_413(asgi):
    huge = (b"x" * 4096,) * (MAX_BODY_BYTES // 4096 + 3)
    assert run(asgi, "POST", "/match", [("X-Match-Key", KEY)], huge)[0] == 413


def test_lifespan_startup_and_shutdown_are_acknowledged(asgi):
    messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message["type"])

    asyncio.run(asgi({"type": "lifespan"}, receive, send))
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
