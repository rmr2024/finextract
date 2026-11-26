"""Embedding and hybrid retrievers (optional: `pip install -e ".[embed]"`).

Same interface as BM25: `search(query, k, numeric_boost) -> [chunk index, ...]`.

- EmbeddingRetriever: cosine similarity between the query and each chunk, using a
  sentence-transformers model (default all-MiniLM-L6-v2). Chunk embeddings are cached on disk per
  filing, keyed by model and a hash of the chunks, so re-runs don't re-encode.
- HybridRetriever: Reciprocal Rank Fusion (k=60) of an unboosted BM25 ranking and the embedding
  ranking, then multiplied by table_boost (applied once, after fusion).

`encode` can be injected (a function from a list of strings to a 2-D array), which is how the tests
run without downloading a model.
"""
import hashlib
import os
import re
from pathlib import Path

from .retrieve import BM25, table_boost

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RRF_K = 60

_models = {}


def default_model():
    return os.environ.get("FINEXTRACT_EMBED_MODEL") or DEFAULT_MODEL


def st_encoder(model_name):
    """A cached sentence-transformers encode function for `model_name`."""
    if model_name not in _models:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise SystemExit('The embed retriever needs the embed extra: pip install -e ".[embed]"')
        _models[model_name] = SentenceTransformer(model_name, device="cpu")
    model = _models[model_name]
    return lambda texts: model.encode(list(texts), batch_size=32, show_progress_bar=False,
                                      convert_to_numpy=True)


def _normalize(m):
    import numpy as np
    m = np.asarray(m, dtype=np.float32)
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(n == 0, 1.0, n)


class EmbeddingRetriever:
    def __init__(self, chunks, model=None, encode=None, cache_dir=None, cache_key=None):
        import numpy as np
        self.docs = chunks
        self.model = model or default_model()
        self.encode = encode or st_encoder(self.model)
        self.cache_path = None
        if cache_dir and chunks:
            h = hashlib.sha256("\x00".join(chunks).encode("utf-8")).hexdigest()[:16]
            safe_model = re.sub(r"[^A-Za-z0-9_.-]", "_", self.model)
            safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", cache_key or "filing")
            self.cache_path = Path(cache_dir) / safe_model / f"{safe_key}-{h}.npy"
        if self.cache_path and self.cache_path.exists():
            self.emb = np.load(self.cache_path)
        else:
            self.emb = _normalize(self.encode(chunks)) if chunks else np.zeros((0, 1), dtype=np.float32)
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.cache_path.with_name(self.cache_path.stem + ".tmp.npy")
                np.save(tmp, self.emb)
                os.replace(tmp, self.cache_path)

    def scores(self, query):
        """Cosine similarity of `query` to every chunk."""
        if not self.docs:
            return []
        q = _normalize(self.encode([query]))[0]
        return (self.emb @ q).tolist()

    def ranking(self, query):
        s = self.scores(query)
        return sorted(range(len(s)), key=lambda i: -s[i])

    def search(self, query, k=6, numeric_boost=0.15):
        """Top-k by cosine similarity. table_boost is not applied here; see HybridRetriever."""
        return self.ranking(query)[:k]


class HybridRetriever:
    def __init__(self, chunks, model=None, encode=None, cache_dir=None, cache_key=None, rrf_k=RRF_K):
        self.docs = chunks
        self.bm25 = BM25(chunks)
        self.embed = EmbeddingRetriever(chunks, model, encode, cache_dir, cache_key)
        self.model = self.embed.model
        self.rrf_k = rrf_k

    def fused_scores(self, query, numeric_boost=0.15):
        """{chunk index: table_boost * sum over rankings of 1 / (rrf_k + rank)}, ranks starting at 1."""
        lists = [self.bm25.search(query, k=len(self.docs), numeric_boost=0.0), self.embed.ranking(query)]
        fused = {}
        for ranked in lists:
            for rank, i in enumerate(ranked, 1):
                fused[i] = fused.get(i, 0.0) + 1.0 / (self.rrf_k + rank)
        return {i: s * table_boost(self.docs[i], numeric_boost) for i, s in fused.items()}

    def search(self, query, k=6, numeric_boost=0.15):
        s = self.fused_scores(query, numeric_boost)
        return sorted(s, key=lambda i: (-s[i], i))[:k]
