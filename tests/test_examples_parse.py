from pathlib import Path

import pytest

from imgflip_memes.parse import parse_examples

FIXTURE = Path(__file__).parent / "fixtures" / "meme_page_whisper.html"


@pytest.fixture(scope="module")
def examples():
    return parse_examples(FIXTURE.read_text())


def card(title="T", alt="T | a; b | image tagged in x,y | made w/ Imgflip meme maker",
         author='<a class="u-username" href="/user/Bob">Bob</a>', stats="1,234 views, 5 upvotes",
         href="/i/abc123"):
    author_html = f'<div class="base-author">by {author}</div>' if author else ""
    return (
        f'<div class="base-unit clearfix"><h2 class="base-unit-title"><a href="{href}">{title}</a></h2>'
        f'<img class="base-img" alt="{alt}" src="//i.imgflip.com/abc123.jpg"/>'
        f'<div class="base-info">{author_html}<div class="base-view-count">{stats}</div></div></div>'
    )


def test_every_example_on_the_page_is_parsed(examples):
    assert len(examples) == 14


def test_first_example_fields(examples):
    first = examples[0]
    assert first.example_id == "b0mblg"
    assert first.url == "https://imgflip.com/i/b0mblg"
    assert first.title == "And I'm not even being joking dawg"
    assert first.author == "Catword"
    assert first.author_url == "https://imgflip.com/user/Catword"
    assert (first.views, first.upvotes, first.comments) == (7010, 7, 0)
    assert first.box_texts == (
        "Just because someone is a celebrity doesn't mean they're god",
        "Modern society:",
    )
    assert first.tags == ("whisper and goosebumps",)
    assert "Modern society:" in first.caption_raw


def test_multiple_tags_split(examples):
    assert examples[1].tags == ("whisper and goosebumps", "relatable", "relatable memes")


def test_every_example_has_an_author_and_caption(examples):
    assert all(e.author for e in examples)
    assert all(e.box_texts for e in examples)


def test_comment_count_parsed():
    (e,) = parse_examples(card(stats="3,673 views, 57 upvotes, 43 comments"))
    assert (e.views, e.upvotes, e.comments) == (3673, 57, 43)


def test_missing_tag_segment_gives_empty_tags():
    (e,) = parse_examples(card(alt="T | only text | made w/ Imgflip meme maker"))
    assert e.tags == () and e.box_texts == ("only text",)


def test_title_containing_pipe_is_handled():
    (e,) = parse_examples(card(title="a | b", alt="a | b | one; two | image tagged in z | made w/ Imgflip meme maker"))
    assert e.title == "a | b" and e.box_texts == ("one", "two")


def test_missing_author_is_none_not_dropped():
    (e,) = parse_examples(card(author=""))
    assert e.author is None and e.author_url is None


def test_card_without_link_is_skipped():
    assert parse_examples('<div class="base-unit"><h2 class="base-unit-title">x</h2></div>') == ()


def test_page_without_examples_returns_empty_tuple():
    assert parse_examples("<html><body></body></html>") == ()


def test_anonymous_author_is_kept_without_a_profile_url(examples):
    anonymous = next(e for e in examples if e.example_id == "75ycc5")
    assert anonymous.author == "anonymous"
    assert anonymous.author_url is None
    assert (anonymous.views, anonymous.upvotes, anonymous.comments) == (349392, 253, 14)


def test_title_with_different_whitespace_does_not_leak_into_first_box():
    # imgflip writes the title with a double space before the pipe in the alt text.
    alt = "Peter parker reading a book  | MEANWHILE, IN 1995:; WAYS TO DIE | image tagged in x | made w/ Imgflip meme maker"
    (e,) = parse_examples(card(title="Peter parker reading a book", alt=alt))
    assert e.box_texts == ("MEANWHILE, IN 1995:", "WAYS TO DIE")
    assert "reading a book" not in e.caption_raw


def test_title_only_alt_gives_no_box_text_even_with_extra_spaces():
    (e,) = parse_examples(card(title="Some  Title", alt="Some Title | made w/ Imgflip meme maker"))
    assert e.box_texts == ()
