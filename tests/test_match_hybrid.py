import numpy as np
import pytest

from match_service.hybrid import HybridSearcher
from match_service.index import TemplateIndex
from tests.test_match_index import caption, template

DIM = 4


def vec(*values):
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


class FakeEmbedder:
    """Maps a few known phrases to fixed vectors so ranking is deterministic."""
    def __init__(self, table):
        self.table = table

    def __call__(self, text):
        return self.table[text]


@pytest.fixture
def parts():
    templates = [
        template(1, "Light Monsters", captions=[caption("the monsters in my room when i turn on the lights", 154), caption("me when somebody flips the switch", 5)]),
        template(2, "Hungry Cat", captions=[caption("me wondering why nobody feeds me", 900)]),
        template(3, "Unsafe One", sfw=False, captions=[caption("turn on the lights now", 999)]),
    ]
    picture_vectors = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 0]], dtype=np.float32)
    caption_vectors = np.array([vec(1, 0, 0, 0), vec(0.9, 0.3, 0, 0), vec(0, 1, 0, 0), vec(1, 0, 0, 0)], dtype=np.float32)
    index = TemplateIndex(picture_vectors, templates)
    text = FakeEmbedder({"roommate turns on the light while i work in the dark": vec(1, 0.1, 0, 0)})
    picture = FakeEmbedder({"roommate turns on the light while i work in the dark": vec(1, 0, 0, 0),
                            "a man hunched under a jacket": vec(0, 1, 0, 0)})
    return index, text, picture, caption_vectors


def make(parts):
    index, text, picture, caption_vectors = parts
    return HybridSearcher(index, text_embed=text, caption_vectors=caption_vectors, picture_embed=picture)


SITUATION = "roommate turns on the light while i work in the dark"


def test_situation_ranks_the_relevant_template_first_and_skips_unsafe(parts):
    result = make(parts).search(situation=SITUATION, description=None, k=5, captions_per_template=5)
    names = [m["template"]["name"] for m in result["matches"]]
    assert names[0] == "Light Monsters" and "Unsafe One" not in names
    assert [m["rank"] for m in result["matches"]] == list(range(1, len(names) + 1))


def test_example_captions_are_ordered_by_relevance_to_the_situation(parts):
    top = make(parts).search(situation=SITUATION, description=None, k=1, captions_per_template=2)["matches"][0]
    assert top["example_captions"][0]["box_texts"][0].startswith("the monsters")


def test_analogs_are_individual_captions_with_template_author_and_votes(parts):
    analogs = make(parts).search(situation=SITUATION, description=None, k=3, captions_per_template=1)["analogs"]
    assert analogs and analogs[0]["template"]["name"] == "Light Monsters"
    assert set(analogs[0]) >= {"box_texts", "author", "url", "upvotes", "score", "template"}
    assert all(a["template"]["name"] != "Unsafe One" for a in analogs)


def test_virality_breaks_near_ties_between_analogs():
    templates = [template(1, "A", captions=[caption("same words here", 1)]), template(2, "B", captions=[caption("same words here", 500)])]
    searcher = HybridSearcher(TemplateIndex(np.eye(2, dtype=np.float32), templates),
                              text_embed=FakeEmbedder({"same words here": vec(1, 0)}),
                              caption_vectors=np.array([vec(1, 0), vec(1, 0)], dtype=np.float32),
                              picture_embed=FakeEmbedder({"same words here": vec(1, 0)}))
    analogs = searcher.search(situation="same words here", description=None, k=2, captions_per_template=1)["analogs"]
    assert analogs[0]["template"]["name"] == "B"


def test_description_alone_still_works(parts):
    result = make(parts).search(situation=None, description="a man hunched under a jacket", k=3, captions_per_template=1)
    assert result["matches"][0]["template"]["name"] == "Hungry Cat"


def test_situation_and_description_are_fused(parts):
    result = make(parts).search(situation=SITUATION, description="a man hunched under a jacket", k=3, captions_per_template=1)
    assert {m["template"]["name"] for m in result["matches"]} == {"Light Monsters", "Hungry Cat"}


def test_needs_at_least_one_input(parts):
    with pytest.raises(ValueError):
        make(parts).search(situation=None, description=None, k=3, captions_per_template=1)


def test_caption_vector_count_must_match_caption_count(parts):
    index, text, picture, caption_vectors = parts
    with pytest.raises(ValueError, match="caption"):
        HybridSearcher(index, text_embed=text, caption_vectors=caption_vectors[:2], picture_embed=picture)


def test_caption_vectors_load_as_float32(tmp_path):
    from match_service.data import load_caption_vectors
    np.save(tmp_path / "caption_vectors.npy", np.ones((3, 4), dtype=np.float16))
    loaded = load_caption_vectors(tmp_path)
    assert loaded.dtype == np.float32 and loaded.shape == (3, 4)


# ---- photo vector (photo-to-picture and photo-to-caption matching) ----

def photo_parts():
    templates = [
        template(1, "Light Monsters", captions=[caption("the monsters in my room when i turn on the lights", 154)]),
        template(2, "Hungry Cat", captions=[caption("me wondering why nobody feeds me", 900)]),
        template(3, "Hiding Guy", captions=[caption("me hiding from my problems", 50)]),
    ]
    pictures = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]], dtype=np.float32)
    captions = np.array([vec(1, 0, 0, 0), vec(0, 1, 0, 0), vec(0, 0, 1, 0)], dtype=np.float32)
    fake = FakeEmbedder({"roommate turns on the light while i work in the dark": vec(1, 0.1, 0, 0)})
    return HybridSearcher(TemplateIndex(pictures, templates), text_embed=fake, caption_vectors=captions, picture_embed=fake)


def test_photo_vector_gets_its_own_slots_in_the_candidate_pool():
    searcher = photo_parts()
    plain = {m["template"]["name"] for m in searcher.search(situation=SITUATION, description=None, k=2, captions_per_template=1)["matches"]}
    with_photo = {m["template"]["name"] for m in searcher.search(situation=SITUATION, description=None, k=2, captions_per_template=1,
                                                                 photo_vector=vec(0, 0, 1, 0))["matches"]}
    assert "Light Monsters" in plain and "Hiding Guy" not in plain
    assert {"Light Monsters", "Hiding Guy"} == with_photo  # one slot from the text side, one from the photo side


def test_pool_has_no_duplicate_templates_and_is_ordered_by_fused_score():
    result = photo_parts().search(situation=SITUATION, description=None, k=3, captions_per_template=1, photo_vector=vec(1, 0, 0, 0))
    names = [m["template"]["name"] for m in result["matches"]]
    assert len(names) == len(set(names)) == 3
    scores = [m["score"] for m in result["matches"]]
    assert scores == sorted(scores, reverse=True)


def test_photo_vector_alone_works_without_any_text():
    result = photo_parts().search(situation=None, description=None, k=1, captions_per_template=1, photo_vector=vec(0, 1, 0, 0))
    assert result["matches"][0]["template"]["name"] == "Hungry Cat"
    assert result["analogs"] == []


def test_photo_vector_with_wrong_dimension_is_rejected():
    with pytest.raises(ValueError):
        photo_parts().search(situation=SITUATION, description=None, k=1, captions_per_template=1, photo_vector=vec(1, 0))


# ---- caller-supplied vectors (no embedding model inside the service) ----

def vector_only_searcher():
    templates = [
        template(1, "Light Monsters", captions=[caption("the monsters in my room when i turn on the lights", 154)]),
        template(2, "Hungry Cat", captions=[caption("me wondering why nobody feeds me", 900)]),
    ]
    pictures = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
    captions = np.array([vec(1, 0, 0, 0), vec(0, 1, 0, 0)], dtype=np.float32)
    return HybridSearcher(TemplateIndex(pictures, templates), text_embed=None, caption_vectors=captions, picture_embed=None)


def test_situation_vector_replaces_the_embedding_callable():
    result = vector_only_searcher().search(situation="roommate turns on the light", description=None, k=2,
                                           captions_per_template=1, situation_vector=vec(1, 0.1, 0, 0))
    assert result["matches"][0]["template"]["name"] == "Light Monsters"
    assert result["analogs"][0]["template"]["name"] == "Light Monsters"


def test_description_vector_drives_picture_matching():
    result = vector_only_searcher().search(situation=None, description="a cat", k=1, captions_per_template=1,
                                           description_vector=vec(0, 1, 0, 0))
    assert result["matches"][0]["template"]["name"] == "Hungry Cat"


def test_situation_text_without_a_vector_or_embedder_is_an_error():
    with pytest.raises(ValueError, match="situation_vector"):
        vector_only_searcher().search(situation="roommate turns on the light", description=None, k=1, captions_per_template=1)


def test_vector_only_service_needs_an_embedder_for_text_unless_vectors_are_supplied():
    # keywords still work from the text alone; meaning/pictures come from the supplied vectors
    result = vector_only_searcher().search(situation="monsters when i turn on the lights", description=None, k=2,
                                           captions_per_template=1, situation_vector=vec(1, 0, 0, 0))
    assert result["matches"][0]["template"]["name"] == "Light Monsters"


# ---- explainability: which search found each template ----

def test_each_match_says_which_searches_ranked_it_near_the_top():
    result = photo_parts().search(situation=SITUATION, description=None, k=2, captions_per_template=1, photo_vector=vec(0, 0, 1, 0))
    by_name = {m["template"]["name"]: m for m in result["matches"]}
    assert "photo_picture" in by_name["Hiding Guy"]["found_by"]
    assert "photo_picture" not in by_name["Light Monsters"]["found_by"]
    assert {"meaning", "situation_picture"} <= set(by_name["Light Monsters"]["found_by"])
    assert all(isinstance(m["found_by"], list) for m in result["matches"])


def test_found_by_only_uses_the_searches_that_actually_ran():
    result = vector_only_searcher().search(situation=None, description="a cat", k=1, captions_per_template=1, description_vector=vec(0, 1, 0, 0))
    assert result["matches"][0]["found_by"] == ["description_picture"]


def test_trace_lists_the_top_templates_of_every_search_with_scores():
    trace = photo_parts().search(situation=SITUATION, description=None, k=3, captions_per_template=1, photo_vector=vec(0, 0, 1, 0))["trace"]
    assert set(trace) == {"keywords", "meaning", "situation_picture", "photo_picture", "photo_caption"}
    top = trace["photo_picture"][0]
    assert top["name"] == "Hiding Guy" and isinstance(top["score"], float)
    assert all(len(entries) <= 3 for entries in trace.values())


def test_unsafe_templates_never_appear_in_found_by_or_trace(parts):
    result = make(parts).search(situation=SITUATION, description=None, k=5, captions_per_template=1)
    assert all("Unsafe One" != e["name"] for entries in result["trace"].values() for e in entries)
    assert all("Unsafe One" != m["template"]["name"] for m in result["matches"])
