import re
from pathlib import Path

import pytest

from imgflip_memes.parse import ParseError, parse_generator, parse_listing

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def listing_html() -> str:
    return (FIXTURES / "listing_page2.html").read_text()


@pytest.fixture(scope="module")
def user_template_html() -> str:
    return (FIXTURES / "generator_user_template.html").read_text()


@pytest.fixture(scope="module")
def generator_html() -> str:
    return (FIXTURES / "generator_drake.html").read_text()


class TestParseListing:
    def test_returns_all_forty_templates(self, listing_html):
        assert len(parse_listing(listing_html)) == 40

    def test_entry_has_slug_name_and_absolute_image_url(self, listing_html):
        entry = parse_listing(listing_html)[0]
        assert entry.slug
        assert entry.name
        assert entry.image_url.startswith("https://i.imgflip.com/")

    def test_numeric_id_extracted_when_link_has_one(self, listing_html):
        by_slug = {e.slug: e for e in parse_listing(listing_html)}
        assert by_slug["Whisper-and-Goosebumps"].template_id == 101956210

    def test_numeric_id_is_none_for_slug_only_links(self):
        html = (
            '<div class="mt-box"><h3 class="mt-title">'
            '<a title="This Is Fine Meme" href="/meme/This-Is-Fine">This Is Fine</a></h3>'
            '<div class="mt-img-wrap"><a href="/meme/This-Is-Fine">'
            '<img src="//i.imgflip.com/4/wxica.jpg"/></a></div></div>'
        )
        (entry,) = parse_listing(html)
        assert entry.slug == "This-Is-Fine"
        assert entry.template_id is None
        assert entry.image_url == "https://i.imgflip.com/4/wxica.jpg"

    def test_slugs_are_unique(self, listing_html):
        slugs = [e.slug for e in parse_listing(listing_html)]
        assert len(slugs) == len(set(slugs))

    def test_empty_page_returns_empty_tuple(self):
        assert parse_listing("<html><body>nothing</body></html>") == ()


class TestParseGenerator:
    def test_selects_entry_by_init_meme_index(self, generator_html):
        detail = parse_generator(generator_html, "Drake-Hotline-Bling")
        assert detail.asset_id == 181913649
        assert detail.name == "Drake Hotline Bling"
        assert (detail.width, detail.height) == (1200, 1200)

    def test_init_meme_index_other_than_zero(self, generator_html):
        html = generator_html.replace("initMeme='0'", "initMeme='1'")
        assert parse_generator(html, "Two-Buttons").asset_id == 87743020

    def test_user_template_object_shape_uses_U_key(self, user_template_html):
        detail = parse_generator(user_template_html, "Anakin-Padme-4-Panel", template_id=322841258)
        assert detail.asset_id == 322841258
        assert detail.name == "Anakin Padme 4 Panel"
        assert len(detail.boxes) >= 2
        assert detail.boxes_explicit is True

    def test_user_template_with_wrong_id_is_rejected(self, user_template_html):
        with pytest.raises(ParseError):
            parse_generator(user_template_html, "Anakin-Padme-4-Panel", template_id=1)

    def test_redirected_generic_page_is_rejected(self, generator_html):
        # slug-only URL for a non-popular template redirects to a generic page showing
        # some other meme; we must not store that meme under the wrong slug.
        with pytest.raises(ParseError):
            parse_generator(generator_html, "Anakin-Padme-4-Panel")

    def test_boxes_carry_positions_and_style(self, generator_html):
        detail = parse_generator(generator_html, "Drake-Hotline-Bling")
        assert len(detail.boxes) == 2
        top, bottom = detail.boxes
        assert (top.x, top.y) == pytest.approx((612.24, 12.24), abs=0.01)
        assert bottom.y > top.y
        assert top.font == "arial"
        assert top.force_caps is False

    def test_boxes_without_type_key_and_null_rotation_are_kept(self, generator_html):
        html = generator_html.replace("initMeme='0'", "initMeme='2'")
        detail = parse_generator(html, "Distracted-Boyfriend")
        assert len(detail.boxes) >= 3
        assert detail.boxes[0].rotation == 0

    def test_empty_default_settings_falls_back_to_default_box_count(self, generator_html):
        html = generator_html.replace("initMeme='0'", "initMeme='%s'" % _index_of(generator_html, "Disaster-Girl"))
        detail = parse_generator(html, "Disaster-Girl")
        assert detail.boxes == ()
        assert detail.boxes_explicit is False
        assert detail.box_count == 2

    def test_alt_names_split_into_tuple(self, generator_html):
        detail = parse_generator(generator_html, "Drake-Hotline-Bling")
        assert "drakeposting" in detail.alt_names
        assert all(n == n.strip() and n for n in detail.alt_names)

    def test_safe_for_work_is_bool(self, generator_html):
        assert parse_generator(generator_html, "Drake-Hotline-Bling").safe_for_work is True

    def test_page_without_embedded_json_raises(self):
        with pytest.raises(ParseError):
            parse_generator("<html></html>", "Drake-Hotline-Bling")

    def test_missing_init_meme_raises(self, generator_html):
        with pytest.raises(ParseError):
            parse_generator(generator_html.replace("initMeme='0'", ""), "Drake-Hotline-Bling")


def _index_of(html: str, url_name: str) -> int:
    import json, re
    start = re.search(r"\bmemes=(?=\[)", html)
    memes, _ = json.JSONDecoder().raw_decode(html[start.end():])
    return next(i for i, m in enumerate(memes) if m["url_name"] == url_name)


class TestMalformedEmbeddedData:
    def test_non_string_alt_names_become_empty(self, generator_html):
        # imgflip sometimes stores altNames as a number (e.g. 7) instead of text.
        html = re.sub(r'"altNames":"[^"]*"', '"altNames":7', generator_html, count=1)
        assert parse_generator(html, "Drake-Hotline-Bling").alt_names == ()

    def test_entry_with_unusable_fields_raises_parse_error_not_a_crash(self, generator_html):
        html = generator_html.replace('"id":181913649,', '"id":null,', 1)
        with pytest.raises(ParseError):
            parse_generator(html, "Drake-Hotline-Bling")
