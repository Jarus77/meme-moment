import numpy as np
import pytest

from match_service.lexical import BM25, normalise, tokens


def test_normalise_drops_when_you_opener_and_box_separators():
    assert normalise("WHEN YOU turn on the light / MY PARENTS") == "turn on the light . my parents"
    assert normalise("Me when I see a dog") == "i see a dog"


def test_tokens_drop_stopwords_and_short_words():
    assert tokens("The roommate turns on a BRIGHT light") == ["roommate", "turns", "bright", "light"]


def test_matching_document_scores_highest():
    docs = [tokens(t) for t in ["monsters in my room when i turn on the lights", "cat wants food now", "roommate fails at cooking"]]
    scores = BM25(docs).scores(tokens("roommate turns on the lights"))
    assert int(np.argmax(scores)) == 0 or int(np.argmax(scores)) == 2
    assert scores[1] == 0.0


def test_rarer_terms_weigh_more_than_common_ones():
    docs = [tokens(t) for t in ["light light light", "light unicorn", "light", "light", "light"]]
    scores = BM25(docs).scores(["unicorn"])
    assert scores[1] > 0 and scores[0] == 0


def test_unknown_or_empty_query_scores_zero_everywhere():
    bm = BM25([tokens("a cat sat"), tokens("dog barks loudly")])
    assert not bm.scores(tokens("zzzz")).any()
    assert not bm.scores([]).any()


def test_empty_document_list_is_rejected():
    with pytest.raises(ValueError):
        BM25([])
