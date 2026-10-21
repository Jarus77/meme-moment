import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from match_service.app import MatchApp
from match_service.index import TemplateIndex
from match_service.server import make_server
from tests.test_match_app import FakeEncoder
from tests.test_match_index import template


@pytest.fixture
def base_url():
    app = MatchApp(TemplateIndex(np.array([[1, 0, 0]], dtype=np.float32), [template(1, "Alpha")]),
                   FakeEncoder(), "k", "m")
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def call(url, data=None, key=None):
    request = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json", **({"X-Match-Key": key} if key else {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_health_over_real_http(base_url):
    assert call(base_url + "/health") == (200, {"ok": True, "templates": 1, "model": "m"})


def test_match_over_real_http_with_key(base_url):
    status, body = call(base_url + "/match", {"description": "a man reading"}, key="k")
    assert status == 200 and body["matches"][0]["template"]["name"] == "Alpha"


def test_match_without_key_is_401_over_http(base_url):
    assert call(base_url + "/match", {"description": "a man reading"})[0] == 401
