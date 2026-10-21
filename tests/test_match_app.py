import json

import numpy as np
import pytest

from match_service.app import MAX_BODY_BYTES, MatchApp
from match_service.index import TemplateIndex
from tests.test_match_index import template

KEY = "secret-key"


class FakeEncoder:
    def __init__(self, ready=True):
        self.ready = ready
        self.seen: list[str] = []

    def encode(self, text: str) -> np.ndarray:
        self.seen.append(text)
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)


@pytest.fixture
def app():
    vectors = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    index = TemplateIndex(vectors, [template(1, "Alpha"), template(2, "Beta")])
    return MatchApp(index=index, encoder=FakeEncoder(), key=KEY, model_name="test-model")


def post(app, body, key=KEY, path="/match"):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {"X-Match-Key": key} if key is not None else {}
    return app.handle("POST", path, headers, raw)


def test_health_needs_no_key(app):
    status, body = app.handle("GET", "/health", {}, b"")
    assert status == 200 and body == {"ok": True, "templates": 2, "model": "test-model"}


def test_match_returns_ranked_contract_shape(app):
    status, body = post(app, {"description": "a man reading a book", "k": 2})
    assert status == 200 and body["model"] == "test-model"
    assert [m["template"]["name"] for m in body["matches"]] == ["Alpha", "Beta"]


def test_defaults_apply_when_optional_fields_omitted(app):
    status, body = post(app, {"description": "a man reading a book"})
    assert status == 200 and len(body["matches"]) == 2


def test_missing_or_wrong_key_is_401(app):
    assert post(app, {"description": "abc def"}, key=None)[0] == 401
    assert post(app, {"description": "abc def"}, key="nope")[0] == 401


@pytest.mark.parametrize("body", [
    {}, {"description": "hi"}, {"description": "x" * 601}, {"description": 5},
    {"description": "fine text", "k": 0}, {"description": "fine text", "k": 31},
    {"description": "fine text", "k": "3"}, {"description": "fine text", "captions_per_template": 21},
    {"description": "fine text", "captions_per_template": -1},
])
def test_invalid_input_is_400_with_message(app, body):
    status, payload = post(app, body)
    assert status == 400 and payload["error"]


def test_bad_json_is_400(app):
    assert post(app, b"{not json")[0] == 400
    assert post(app, b"[1,2]")[0] == 400


def test_oversized_body_is_413(app):
    assert post(app, b"x" * (MAX_BODY_BYTES + 1))[0] == 413


def test_encoder_not_ready_is_503():
    vectors = np.array([[1, 0, 0]], dtype=np.float32)
    app = MatchApp(TemplateIndex(vectors, [template(1, "A")]), FakeEncoder(ready=False), KEY, "m")
    assert post(app, {"description": "abc def"})[0] == 503


def test_unknown_path_404_and_wrong_method_405(app):
    assert app.handle("GET", "/nope", {}, b"")[0] == 404
    assert app.handle("GET", "/match", {"X-Match-Key": KEY}, b"")[0] == 405


def test_description_is_trimmed_before_encoding(app):
    post(app, {"description": "   a man reading   "})
    assert app.encoder.seen == ["a man reading"]


def test_empty_key_refuses_to_construct():
    with pytest.raises(ValueError):
        MatchApp(TemplateIndex(np.eye(3, dtype=np.float32), [template(i, f"T{i}") for i in range(3)]),
                 FakeEncoder(), key="", model_name="m")


class FakeHybrid:
    def __init__(self):
        self.calls = []

    def search(self, situation, description, k, captions_per_template, photo_vector=None):
        self.calls.append((situation, description, k, captions_per_template))
        return {"matches": [{"rank": 1, "score": 1.0, "template": {"name": "H"}, "example_captions": []}],
                "analogs": [{"box_texts": ["x"], "author": "a", "url": "u", "upvotes": 1, "score": 1.0, "template": {}}]}


@pytest.fixture
def hybrid_app():
    vectors = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    index = TemplateIndex(vectors, [template(1, "Alpha"), template(2, "Beta")])
    hybrid = FakeHybrid()
    return MatchApp(index, FakeEncoder(), KEY, "m", hybrid=hybrid), hybrid


def test_situation_uses_hybrid_search_and_returns_analogs(hybrid_app):
    app, hybrid = hybrid_app
    status, body = post(app, {"situation": "roommate turns on the light", "description": "a man under a jacket", "k": 4})
    assert status == 200 and body["analogs"][0]["author"] == "a" and body["matches"][0]["template"]["name"] == "H"
    assert hybrid.calls == [("roommate turns on the light", "a man under a jacket", 4, 8)]


def test_situation_alone_is_enough(hybrid_app):
    app, hybrid = hybrid_app
    assert post(app, {"situation": "roommate turns on the light"})[0] == 200
    assert hybrid.calls[0][1] is None


def test_description_only_keeps_the_original_behaviour(hybrid_app):
    app, hybrid = hybrid_app
    status, body = post(app, {"description": "a man reading a book"})
    assert status == 200 and "analogs" not in body and hybrid.calls == []


def test_situation_without_hybrid_falls_back_to_picture_search(app):
    status, body = post(app, {"situation": "a man reading a book"})
    assert status == 200 and "analogs" not in body and body["matches"]


def test_needs_description_or_situation(app):
    status, body = post(app, {"k": 3})
    assert status == 400 and "situation" in body["error"]


@pytest.mark.parametrize("situation", ["hi", "x" * 601, 5, ["a"]])
def test_invalid_situation_is_400(app, situation):
    assert post(app, {"situation": situation})[0] == 400


def test_photo_vector_is_passed_to_hybrid_search(hybrid_app):
    app, hybrid = hybrid_app
    vector = [0.1] * 3
    # FakeHybrid.search takes no photo_vector, so extend it for this test
    seen = {}
    original = hybrid.search
    hybrid.search = lambda situation, description, k, captions_per_template, photo_vector=None: (
        seen.update(photo_vector=photo_vector) or original(situation, description, k, captions_per_template))
    status, _ = post(app, {"situation": "roommate turns on the light", "photo_vector": vector})
    assert status == 200 and seen["photo_vector"] == vector


@pytest.mark.parametrize("bad", ["abc", [1, 2, "x"], [], [float("nan")] * 3, [1.0] * 5000, {"a": 1}])
def test_invalid_photo_vector_is_400(hybrid_app, bad):
    app, _ = hybrid_app
    raw = json.dumps({"situation": "roommate turns on the light", "photo_vector": bad}, allow_nan=True).encode()
    assert post(app, raw)[0] == 400


def test_photo_vector_alone_is_a_valid_request(hybrid_app):
    app, _ = hybrid_app
    assert post(app, {"photo_vector": [0.1] * 3})[0] == 200


def test_photo_vector_with_the_wrong_dimension_is_400(hybrid_app):
    app, _ = hybrid_app
    status, body = post(app, {"situation": "roommate turns on the light", "photo_vector": [0.1] * 5})
    assert status == 400 and "photo_vector" in body["error"]


def test_photo_vector_without_hybrid_does_picture_search(app):
    status, body = post(app, {"photo_vector": [1.0, 0.0, 0.0]})
    assert status == 200 and body["matches"][0]["template"]["name"] == "Alpha"


# ---- v2: vectors supplied by the caller, no encoder in the service ----

@pytest.fixture
def vector_app():
    vectors = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    index = TemplateIndex(vectors, [template(1, "Alpha"), template(2, "Beta")])
    hybrid = FakeHybrid()
    seen = {}
    original = hybrid.search
    hybrid.search = lambda situation, description, k, captions_per_template, **kw: (seen.update(kw) or original(situation, description, k, captions_per_template))
    return MatchApp(index, None, KEY, "m", hybrid=hybrid), seen


def test_service_without_encoder_never_returns_503(vector_app):
    app, _ = vector_app
    assert post(app, {"situation": "roommate turns on the light", "situation_vector": [0.1, 0.2, 0.3]})[0] == 200


def test_all_three_vectors_are_forwarded(vector_app):
    app, seen = vector_app
    body = {"situation": "roommate turns on the light", "situation_vector": [1, 0, 0], "description_vector": [0, 1, 0], "photo_vector": [0, 0, 1]}
    assert post(app, body)[0] == 200
    assert seen == {"situation_vector": [1.0, 0.0, 0.0], "description_vector": [0.0, 1.0, 0.0], "photo_vector": [0.0, 0.0, 1.0]}


@pytest.mark.parametrize("name", ["situation_vector", "description_vector"])
def test_other_vectors_are_validated_like_photo_vector(vector_app, name):
    app, _ = vector_app
    assert post(app, {"situation": "roommate turns on the light", name: [1, 2]})[0] == 400
    assert post(app, {"situation": "roommate turns on the light", name: "abc"})[0] == 400


def test_without_encoder_and_without_any_vector_text_only_is_a_clear_400():
    vectors = np.array([[1, 0, 0]], dtype=np.float32)
    app = MatchApp(TemplateIndex(vectors, [template(1, "Alpha")]), None, KEY, "m")
    status, body = post(app, {"description": "a man reading"})
    assert status == 400 and "vector" in body["error"]
