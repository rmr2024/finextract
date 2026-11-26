# Retriever selection (dev only, fixed before any test split was run)

Rule (declared before the run): the winner is the retriever with the most dev recall@6 hits, and it
counts as beating BM25 only with strictly more hits than BM25. MRR@10 breaks ties.

| Retriever | dev Recall@4 | dev Recall@6 | dev MRR@10 |
|---|---|---|---|
| bm25 | 95.4% (42/44) | 95.4% (42/44) | 0.826 |
| embed | 63.6% (28/44) | 77.2% (34/44) | 0.532 |
| hybrid | 93.1% (41/44) | 100.0% (44/44) | 0.843 |

**Winner: hybrid** (44/44 against 42/44 at @6).

Caveat: at k=4, the `--k` used by the gpt-oss LLM runs, hybrid is 1 hit *below* BM25 on dev (41 vs
42). Hybrid moves MSFT total_liabilities (rank 10 to 4) and NKE total_assets (not in the top 10, to 5)
up. It moves KO total_assets, CAT total_assets and CAT long_term_debt down to ranks 4–5.

Test splits (test5 primary, test15 secondary) are each run once afterwards for all three retrievers,
with no changes.
