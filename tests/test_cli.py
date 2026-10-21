import pytest

from imgflip_memes import __main__ as cli


@pytest.fixture
def calls(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(cli, "crawl", lambda *a, **k: seen.append("crawl") or "stats")
    monkeypatch.setattr(cli, "backfill_images", lambda *a, **k: seen.append("images"))
    monkeypatch.setattr(cli, "crawl_examples", lambda *a, **k: seen.append(f"examples:{k['pages']}") or "stats")
    return seen


def run(tmp_path, *flags):
    return cli.main(["--db", str(tmp_path / "m.db"), "--cache", str(tmp_path / "c"),
                     "--images", str(tmp_path / "i"), *flags])


def test_default_runs_templates_images_then_examples(tmp_path, calls):
    assert run(tmp_path) == 0
    assert calls == ["crawl", "images", "examples:1"]


def test_examples_only_skips_template_crawl(tmp_path, calls):
    run(tmp_path, "--examples-only", "--example-pages", "2")
    assert calls == ["examples:2"]


def test_no_examples_and_no_images(tmp_path, calls):
    run(tmp_path, "--no-examples", "--no-images")
    assert calls == ["crawl"]


def test_repair_examples_flag_only_repairs(tmp_path, calls):
    assert run(tmp_path, "--repair-examples") == 0
    assert calls == []
