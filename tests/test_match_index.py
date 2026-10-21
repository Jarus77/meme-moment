import numpy as np
import pytest

from match_service.index import TemplateIndex


def template(asset_id: int, name: str, sfw: bool = True, captions=None) -> dict:
    return {
        "asset_id": asset_id, "slug": name.replace(" ", "-"), "name": name,
        "source_url": f"https://imgflip.com/meme/{asset_id}/{name.replace(' ', '-')}",
        "image_url": f"https://i.imgflip.com/{asset_id}.jpg", "width": 100, "height": 100,
        "safe_for_work": sfw, "box_count": 2, "boxes_explicit": False, "boxes": [],
        "captions": captions or [],
    }


def caption(text: str, upvotes: int) -> dict:
    return {"box_texts": [text], "author": "Bob", "url": "https://imgflip.com/i/x", "upvotes": upvotes}


@pytest.fixture
def index():
    vectors = np.array([[1, 0, 0], [0, 1, 0], [0.8, 0.6, 0]], dtype=np.float32)
    templates = [
        template(1, "Alpha", captions=[caption("low", 1), caption("high", 9), caption("mid", 5)]),
        template(2, "Beta"),
        template(3, "Gamma"),
    ]
    return TemplateIndex(vectors, templates)


def test_results_are_ranked_by_cosine_similarity(index):
    results = index.search(np.array([1.0, 0.0, 0.0]), k=3, captions_per_template=0)
    assert [r["template"]["name"] for r in results] == ["Alpha", "Gamma", "Beta"]
    assert [r["rank"] for r in results] == [1, 2, 3]
    assert results[0]["score"] == pytest.approx(1.0, abs=1e-4)


def test_query_is_normalised_so_scale_does_not_matter(index):
    a = index.search(np.array([1.0, 0.0, 0.0]), k=1, captions_per_template=0)
    b = index.search(np.array([50.0, 0.0, 0.0]), k=1, captions_per_template=0)
    assert a[0]["score"] == pytest.approx(b[0]["score"])


def test_k_limits_results(index):
    assert len(index.search(np.array([1.0, 0, 0]), k=2, captions_per_template=0)) == 2
    assert len(index.search(np.array([1.0, 0, 0]), k=99, captions_per_template=0)) == 3


def test_captions_most_upvoted_first_and_capped(index):
    top = index.search(np.array([1.0, 0, 0]), k=1, captions_per_template=2)[0]
    assert [c["box_texts"][0] for c in top["example_captions"]] == ["high", "mid"]


def test_not_safe_for_work_templates_are_never_returned():
    vectors = np.array([[1, 0], [0, 1]], dtype=np.float32)
    idx = TemplateIndex(vectors, [template(1, "Unsafe", sfw=False), template(2, "Safe")])
    names = [r["template"]["name"] for r in idx.search(np.array([1.0, 0.0]), k=5, captions_per_template=0)]
    assert names == ["Safe"]


def test_result_exposes_contract_fields_without_internal_captions_key(index):
    result = index.search(np.array([1.0, 0, 0]), k=1, captions_per_template=1)[0]
    assert set(result) == {"rank", "score", "template", "example_captions"}
    assert "captions" not in result["template"]
    assert result["template"]["image_url"].startswith("https://i.imgflip.com/")


def test_mismatched_vector_and_template_counts_rejected():
    with pytest.raises(ValueError):
        TemplateIndex(np.zeros((2, 3), dtype=np.float32), [template(1, "Only")])


def test_wrong_query_dimension_rejected(index):
    with pytest.raises(ValueError):
        index.search(np.array([1.0, 0.0]), k=1, captions_per_template=0)


def test_zero_query_vector_rejected(index):
    with pytest.raises(ValueError):
        index.search(np.zeros(3), k=1, captions_per_template=0)
