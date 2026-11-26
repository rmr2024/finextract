# Retrieval benchmark: BM25 on dev

**Relevant chunk:** a chunk with a table row whose value cell equals the label exactly, using the
verifier's normalisation (`verify._cell_numbers`: label column skipped, `%` cells ignored, `(1,234)` =
-1234; USD fields scaled by the chunk's scale hint, per-share fields unscaled; `numbers_match`,
rel_tol=1e-9). Matching is by value, so the same number appearing in another context also counts.

**Recall@k** = labeled fields with a relevant chunk in the top k / all labeled fields. **MRR@10** = mean
of 1/rank of the first relevant chunk within the top 10 (0 if none). *Unreachable* = no relevant chunk
anywhere in the filing; those fields stay in the denominator. Percentages and MRR are truncated, never
rounded up. Queries are each field's `query` from `config.py`; chunks come from `textproc.chunk_text`,
exactly as in extraction.

| Split | Retriever | n | Recall@3 | Recall@6 | Recall@10 | MRR@10 | Unreachable |
|---|---|---|---|---|---|---|---|
| dev | bm25 | 44 | 93.1% (41/44) | 95.4% (42/44) | 97.7% (43/44) | 0.826 | 0/44 |

Only dev is reported here; test results are in retrieval_comparison.md, run once after the retriever was chosen on dev.

Below rank 6 on dev: MSFT total_liabilities (first relevant chunk at rank 10) and NKE total_assets (not in the top 10). These are the same two fields the extractors missed at k=6.
