# Retrieval comparison: BM25 vs embeddings vs hybrid

Winner chosen on **dev only** (rule: most dev recall@6 hits, strictly more than BM25), committed in
`reports/retrieval_selection.md` before test was run. test5 (primary, 44 labels) and test15 (secondary,
137 labels, includes test5) were each run once afterwards with no changes. Embedding model:
`sentence-transformers/all-MiniLM-L6-v2`. Hybrid = RRF (k=60) of unboosted BM25 + embedding ranks, times table_boost.

**Relevant chunk:** a chunk with a table row whose value cell equals the label exactly, using the
verifier's normalisation (`verify._cell_numbers`: label column skipped, `%` cells ignored, `(1,234)` =
-1234; USD fields scaled by the chunk's scale hint, per-share fields unscaled; `numbers_match`,
rel_tol=1e-9). Matching is by value, so the same number appearing in another context also counts.

**Recall@k** = labeled fields with a relevant chunk in the top k / all labeled fields. **MRR@10** = mean
of 1/rank of the first relevant chunk within the top 10 (0 if none). *Unreachable* = no relevant chunk
anywhere in the filing; those fields stay in the denominator. Percentages and MRR are truncated, never
rounded up. Queries are each field's `query` from `config.py`; chunks come from `textproc.chunk_text`,
exactly as in extraction.

Recall@4 is shown too: the gpt-oss LLM runs used `--k 4`.

| Split | Retriever | n | Recall@3 | Recall@4 | Recall@6 | Recall@10 | MRR@10 | Unreachable |
|---|---|---|---|---|---|---|---|---|
| dev | bm25 | 44 | 93.1% (41/44) | 95.4% (42/44) | 95.4% (42/44) | 97.7% (43/44) | 0.826 | 0/44 |
| dev | embed | 44 | 56.8% (25/44) | 63.6% (28/44) | 77.2% (34/44) | 88.6% (39/44) | 0.532 | 0/44 |
| dev | hybrid (winner) | 44 | 88.6% (39/44) | 93.1% (41/44) | 100.0% (44/44) | 100.0% (44/44) | 0.843 | 0/44 |
| test5 | bm25 | 44 | 93.1% (41/44) | 95.4% (42/44) | 95.4% (42/44) | 95.4% (42/44) | 0.839 | 0/44 |
| test5 | embed | 44 | 68.1% (30/44) | 70.4% (31/44) | 81.8% (36/44) | 86.3% (38/44) | 0.612 | 0/44 |
| test5 | hybrid (winner) | 44 | 90.9% (40/44) | 95.4% (42/44) | 97.7% (43/44) | 100.0% (44/44) | 0.871 | 0/44 |
| test15 | bm25 | 137 | 86.8% (119/137) | 88.3% (121/137) | 89.7% (123/137) | 91.2% (125/137) | 0.773 | 9/137 |
| test15 | embed | 137 | 59.8% (82/137) | 64.2% (88/137) | 72.2% (99/137) | 81.7% (112/137) | 0.507 | 9/137 |
| test15 | hybrid (winner) | 137 | 85.4% (117/137) | 88.3% (121/137) | 91.9% (126/137) | 92.7% (127/137) | 0.757 | 9/137 |

**Reading:**
- Embeddings alone are clearly worse than BM25 on every split and cutoff.
- Hybrid beats BM25 at recall@6 on all three splits: dev +2 (44 vs 42), test5 +1 (43 vs 42), test15 +3 (126 vs 123).
- At recall@4, the k the LLM runs use, hybrid only ties BM25 on test5 (42 vs 42) and test15 (121 vs 121), and is 1 below on dev (41 vs 42).
- At recall@3 hybrid is below BM25 everywhere: dev 39 vs 41, test5 40 vs 41, test15 117 vs 119.
- MRR@10: hybrid is higher on dev (0.843 vs 0.826) and test5 (0.871 vs 0.839), and lower on test15 (0.757 vs 0.773).
- Hybrid pulls missed chunks up into ranks 4–6 but pushes some top-3 chunks down. It helps extraction run at k=6, not at k=4.
- test15 has 9 unreachable fields (no chunk with the exact value); no retriever can fix those.
- Differences are 1–3 fields out of 44 or 137: small, and within noise for n=44.
