"""Retrievers and the retrieval benchmark. A fake hashing encoder stands in for the model, so no download."""
import hashlib
import os
import re

import pytest

np = pytest.importorskip("numpy")

from finextract.embed_retrieve import EmbeddingRetriever, HybridRetriever  # noqa: E402
from finextract.retrieval_eval import floor_to, is_relevant, pct  # noqa: E402
from finextract.retrieve import BM25, RETRIEVERS, make_retriever, table_boost  # noqa: E402

DIM = 64


def fake_encode(texts):
    """Deterministic bag-of-words hashing embedding."""
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for r, t in enumerate(texts):
        for w in re.findall(r"[a-z]+", t.lower()):
            out[r, int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
    return out


CHUNKS = [
    "Results of operations discussion and outlook for the year",
    "Consolidated balance sheets | Total assets | 98,585 | 87,764\nTotal liabilities | 77,267 | 68,270",
    "Cash flows | Net cash provided by operating activities | 11,739 | 12,035",
    "Risk factors: competition, regulation, cybersecurity",
]


def test_embedding_retriever_ranks_by_cosine():
    r = EmbeddingRetriever(CHUNKS, model="fake", encode=fake_encode)
    assert r.search("total assets balance sheets", k=1) == [1]
    assert r.search("net cash operating activities", k=1) == [2]
    assert sorted(r.ranking("anything")) == list(range(len(CHUNKS)))


def test_embedding_cache_roundtrip(tmp_path):
    first = EmbeddingRetriever(CHUNKS, model="fake/model", encode=fake_encode, cache_dir=tmp_path, cache_key="EXWD_1")
    assert first.cache_path.exists() and first.cache_path.parent.name == "fake_model"

    def boom(texts):
        if len(texts) > 1:
            raise AssertionError("chunks must come from the cache, not be re-encoded")
        return fake_encode(texts)

    second = EmbeddingRetriever(CHUNKS, model="fake/model", encode=boom, cache_dir=tmp_path, cache_key="EXWD_1")
    assert np.allclose(first.emb, second.emb)
    other = EmbeddingRetriever(CHUNKS[:2], model="fake/model", encode=fake_encode, cache_dir=tmp_path, cache_key="EXWD_1")
    assert other.cache_path != first.cache_path  # different chunks -> different cache file


def test_hybrid_is_rrf_times_table_boost():
    h = HybridRetriever(CHUNKS, model="fake", encode=fake_encode)
    q = "total assets"
    bm = h.bm25.search(q, k=len(CHUNKS), numeric_boost=0.0)
    em = h.embed.ranking(q)
    expected = {}
    for ranked in (bm, em):
        for rank, i in enumerate(ranked, 1):
            expected[i] = expected.get(i, 0.0) + 1 / (60 + rank)
    expected = {i: s * table_boost(CHUNKS[i], 0.15) for i, s in expected.items()}
    got = h.fused_scores(q)
    assert got.keys() == expected.keys() and all(abs(got[i] - expected[i]) < 1e-12 for i in got)
    assert h.search(q, k=1) == [1]
    assert len(h.search(q, k=10)) == len(CHUNKS)  # every chunk is in the embedding ranking


def test_make_retriever():
    assert RETRIEVERS == ("bm25", "embed", "hybrid")
    assert isinstance(make_retriever("bm25", CHUNKS), BM25)
    assert isinstance(make_retriever("embed", CHUNKS, model="fake", encode=fake_encode), EmbeddingRetriever)
    assert isinstance(make_retriever("hybrid", CHUNKS, model="fake", encode=fake_encode), HybridRetriever)
    with pytest.raises(ValueError):
        make_retriever("tfidf", CHUNKS)


def test_is_relevant_uses_verifier_normalisation():
    chunk = "[amounts in millions]\nTotal liabilities | 77,267 | 68,270\nOperating margin | 16.5% | 17.0%"
    assert is_relevant(chunk, 77267e6)
    assert is_relevant(chunk, 68270e6)          # value match: the prior-year column also counts
    assert not is_relevant(chunk, 77267)         # scale applied
    assert not is_relevant(chunk, 16.5, unit="USD/shares")  # % cells ignored
    assert is_relevant("Diluted | 18.81 | 22.05", 18.81, unit="USD/shares")  # per-share: unscaled
    assert is_relevant("[amounts in millions]\nNet loss | (1,234) | 5", -1234e6)


def test_percentages_truncate_never_round_up():
    assert pct(41, 44) == "93.1% (41/44)"       # 93.18 -> 93.1, not 93.2
    assert pct(0, 0) == "n/a (0/0)"
    assert floor_to(0.8269, 3) == 0.826


@pytest.mark.skipif(bool(os.environ.get("CI")) or not os.environ.get("FINEXTRACT_TEST_REAL_EMBED"),
                    reason="real model download; opt in locally with FINEXTRACT_TEST_REAL_EMBED=1, never in CI")
def test_real_model_smoke():
    pytest.importorskip("sentence_transformers")
    r = EmbeddingRetriever(CHUNKS)
    assert r.search("total assets on the balance sheet", k=1) == [1]
