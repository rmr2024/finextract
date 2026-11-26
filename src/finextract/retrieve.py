"""Small dependency-free BM25 retriever over a filing's chunks."""
import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z]+")
_NUM = re.compile(r"\d[\d,]*\.?\d*")
_STOP = {"the", "of", "and", "in", "to", "a", "for", "by", "on", "or", "as", "at", "is", "be", "are", "from"}


def tokenize(text):
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs
        self.tokens = [tokenize(d) for d in docs]
        self.tf = [Counter(t) for t in self.tokens]
        self.lens = [len(t) for t in self.tokens]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df = Counter()
        for t in self.tokens:
            df.update(set(t))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.k1, self.b = k1, b

    def score(self, query, i):
        tf, dl = self.tf[i], self.lens[i] or 1
        s = 0.0
        for w in tokenize(query):
            if w not in tf:
                continue
            f = tf[w]
            s += self.idf.get(w, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avg or 1)))
        return s

    def search(self, query, k=6, numeric_boost=0.15):
        """Top-k chunk indices. Chunks dense with numbers (i.e. financial tables) get a mild boost."""
        scored = []
        for i, d in enumerate(self.docs):
            s = self.score(query, i)
            if s <= 0:
                continue
            scored.append((s * table_boost(d, numeric_boost), i))
        scored.sort(reverse=True)
        return [i for _, i in scored[:k]]


def table_boost(chunk, numeric_boost=0.15):
    """Score multiplier for chunks dense with numbers (numbers per 100 chars, capped at 5)."""
    density = len(_NUM.findall(chunk)) / max(1, len(chunk) / 100)
    return 1 + numeric_boost * min(density, 5)


RETRIEVERS = ("bm25", "embed", "hybrid")


def make_retriever(name, chunks, **kw):
    """Build a retriever with a search(query, k, numeric_boost) method over `chunks`.

    embed/hybrid accept model, encode, cache_dir and cache_key (see embed_retrieve.py); bm25 ignores them.
    """
    if name == "bm25":
        return BM25(chunks)
    if name in ("embed", "hybrid"):
        from .embed_retrieve import EmbeddingRetriever, HybridRetriever
        cls = EmbeddingRetriever if name == "embed" else HybridRetriever
        return cls(chunks, **kw)
    raise ValueError(f"unknown retriever {name!r}; expected one of {RETRIEVERS}")
