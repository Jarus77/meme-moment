import pytest

from imgflip_memes.fetch import FetchError, PoliteFetcher, is_allowed


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok", content: bytes = b"", content_type: str = ""):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = {"Content-Type": content_type}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.headers: dict[str, str] = {}

    def get(self, url, timeout):
        self.calls += 1
        return self.responses.pop(0)


def make_fetcher(tmp_path, responses, sleeps=None, **kwargs):
    sleeps = sleeps if sleeps is not None else []
    session = FakeSession(responses)
    fetcher = PoliteFetcher(
        cache_dir=tmp_path, delay=1.0, session=session, sleep=sleeps.append, **kwargs
    )
    return fetcher, session, sleeps


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("https://imgflip.com/memetemplates?page=2", True),
        ("https://imgflip.com/memegenerator/Drake-Hotline-Bling", True),
        ("https://imgflip.com/orig/abc", False),
        ("https://imgflip.com/browse/anything", False),
    ],
)
def test_robots_rules(url, allowed):
    assert is_allowed(url) is allowed


def test_disallowed_url_is_refused_without_a_request(tmp_path):
    fetcher, session, _ = make_fetcher(tmp_path, [])
    with pytest.raises(FetchError):
        fetcher.get("https://imgflip.com/orig/abc")
    assert session.calls == 0


def test_second_get_is_served_from_cache(tmp_path):
    fetcher, session, _ = make_fetcher(tmp_path, [FakeResponse(text="hello")])
    assert fetcher.get("https://imgflip.com/a") == "hello"
    assert fetcher.get("https://imgflip.com/a") == "hello"
    assert session.calls == 1


def test_delay_applied_between_live_requests_only(tmp_path):
    fetcher, _, sleeps = make_fetcher(tmp_path, [FakeResponse(), FakeResponse()])
    fetcher.get("https://imgflip.com/a")
    fetcher.get("https://imgflip.com/a")  # cached, no delay
    fetcher.get("https://imgflip.com/b")
    assert len(sleeps) == 2 and all(s == 1.0 for s in sleeps)


def test_retries_transient_errors_then_succeeds(tmp_path):
    fetcher, session, _ = make_fetcher(
        tmp_path, [FakeResponse(503), FakeResponse(429), FakeResponse(text="fine")]
    )
    assert fetcher.get("https://imgflip.com/a") == "fine"
    assert session.calls == 3


def test_gives_up_after_max_retries(tmp_path):
    fetcher, session, _ = make_fetcher(tmp_path, [FakeResponse(503)] * 3, max_retries=3)
    with pytest.raises(FetchError):
        fetcher.get("https://imgflip.com/a")
    assert session.calls == 3


def test_404_is_not_retried(tmp_path):
    fetcher, session, _ = make_fetcher(tmp_path, [FakeResponse(404)])
    with pytest.raises(FetchError):
        fetcher.get("https://imgflip.com/a")
    assert session.calls == 1


def test_get_binary_returns_bytes_and_content_type_without_html_cache(tmp_path):
    fetcher, session, _ = make_fetcher(
        tmp_path, [FakeResponse(content=b"\x89PNG", content_type="image/png")]
    )
    assert fetcher.get_binary("https://i.imgflip.com/x.png") == (b"\x89PNG", "image/png")
    assert list(tmp_path.iterdir()) == []


def test_get_binary_retries_and_refuses_disallowed(tmp_path):
    fetcher, session, _ = make_fetcher(
        tmp_path, [FakeResponse(503), FakeResponse(content=b"ok", content_type="image/jpeg")]
    )
    assert fetcher.get_binary("https://i.imgflip.com/x.jpg")[0] == b"ok"
    with pytest.raises(FetchError):
        fetcher.get_binary("https://imgflip.com/orig/abc.jpg")
