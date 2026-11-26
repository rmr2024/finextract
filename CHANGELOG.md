# Changelog

## v1.1.0 (2026-11-26)

**Added**
- `--retriever {bm25,embed,hybrid}` on `extract` (default `bm25`, so results are unchanged).
  - The retriever and embedding model are recorded per run and per row.
  - `--resume` refuses a retriever mismatch.
- `EmbeddingRetriever`: sentence-transformers, `all-MiniLM-L6-v2` by default, with per-filing
  embeddings cached on disk.
- `HybridRetriever`: RRF (k=60) of BM25 and embeddings, times table_boost.
- The optional `embed` extra.
- `finextract retrieval-eval --split {dev,test5,test15}`: a retrieval-only benchmark (recall@k and
  MRR@10, with relevance judged by the verifier's normalisation). Reports in `reports/retrieval_*`.
- A dashboard screenshot in the README.

**Results** (winner chosen on dev only):
- Hybrid beats BM25 at recall@6:
  - dev 100.0% (44/44) vs 95.4% (42/44);
  - test5 97.7% (43/44) vs 95.4% (42/44);
  - test15 91.9% (126/137) vs 89.7% (123/137).
- At recall@4, hybrid only ties BM25 on test5 and test15.
- Embeddings alone are worse than BM25 on every split.
- BM25 remains the default.

## v1.0.0 (2026-11-01)

First complete release.

**Benchmark results (exact match, n=44 labeled fields per set):**
- gpt-oss-120b + verify: 84.1% on the held-out test set, 93.2% on dev.
- Raw gpt-oss-120b: 75.0% test, 81.8% dev.
- Heuristic: 59.1% test, 68.2% dev.

**Added**
- `finextract verify`: offline snap-to-source verification. It re-reads each answer's number from the
  matched filing line, with no LLM call.
- A held-out test run with a full error breakdown (`docs/DEVLOG.md`).
- A service: SQLite store (`finextract import`), FastAPI endpoints for runs, summaries, filings and
  background extract jobs, and a dashboard at `/` via `finextract serve` (127.0.0.1 by default).
- Docker: `Dockerfile` and `.dockerignore`.
- Prompt versioning: `FINEXTRACT_PROMPT_VERSION`, with `prompt_version` and `prompt_hash` on every run
  and row. `--resume` refuses to mix prompts.
- Documentation: `docs/WRITEUP.md`, `docs/DEVLOG.md`, `ROADMAP.md`, `CONTRIBUTING.md`.

**Changed**
- Headline accuracy is now exact match after scale. The 0.5% figure is kept as `accuracy_tolerant`,
  and values within 0.5% that aren't exact get their own class, `near_miss`.
- The cash field description is versioned: v1 is the default, and v2 excludes restricted cash.

**Removed**
- The intermediate `--limit 1` probe predictions and a labels backup file.

## v0.4.0: hosted LLM runs
- An OpenAI-compatible provider tested against a hosted free tier (gpt-oss-120b).
- Rate limiting:
  - `FINEXTRACT_MIN_INTERVAL` sets the gap between requests;
  - a 429 waits out its Retry-After;
  - a daily limit stops the run cleanly.
- `--resume`: predictions are written row by row, and failed fields are retried.

## v0.3.0: local LLM support
- Ollama, via the OpenAI-compatible API:
  - a context-length warning;
  - JSON mode with a fallback if the server rejects it;
  - `reasoning_effort` for thinking models;
  - a configurable request timeout.

## v0.2.0: held-out split and scale propagation
- `DEV_TICKERS` and `TEST_TICKERS`.
- Table scale hints ("In millions") are carried into chunks that lack them, which removed all scale
  errors.

## v0.1.0: baseline
- EDGAR download, XBRL labels, text and table flattening, BM25 retrieval, a heuristic extractor,
  evaluation with error classes, and an offline demo.
- Windows fixes: UTF-8 everywhere, an atomic text cache, and a regression test.
