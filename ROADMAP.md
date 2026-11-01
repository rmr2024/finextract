# Roadmap

**v1.0 complete.** Everything listed below is shipped:
- The benchmark pipeline: EDGAR download, XBRL labels, BM25 retrieval, heuristic and LLM extractors.
- Exact-match evaluation with error classes.
- Snap-to-source verification.
- Held-out test results.
- The SQLite store, FastAPI service, dashboard and Dockerfile.

The results are in the [README](README.md), and the stage-by-stage detail in
[docs/DEVLOG.md](docs/DEVLOG.md).

## Next

### Accuracy
- **Concept checks in `verify`.** Reject a snapped line whose label contradicts the field definition:
  noncontrolling or consolidated against attributable, current portion, restricted cash, segment rows.
  These are the main grounded-but-wrong errors left on the test set.
- **Decimal-aware column choice.** When the model drops decimals (2 for 2.73), digit distance ties
  across columns. Prefer the current-period column, or the first column, on ties.
- **Retrieval.** 2 fields per set never reach the extractor. Try a larger k for balance-sheet fields,
  or boost chunks under statement headings.
- **Label QA.** Check more labels: 15 so far, plus one tag-fallback mismatch (HD long-term debt).
  Flag fallback-tag labels automatically.
- **Prompt v2.** Run the cash wording that excludes restricted cash on dev (`dev_gptoss_v2`) and
  measure any side effects.

### Benchmark
- **Open benchmark and leaderboard.** A versioned labeled dataset, a scoring script, and a results
  table per model with exact, coverage and confident-wrong.
- **Untagged documents.** Earnings press releases and other filings without XBRL, where extraction is
  actually needed. Ground truth would come from the matching 10-K or 10-Q.
- **More models and more filings.** Compare cost and accuracy across models; break errors down by
  sector and document length.

### Service (Stage 3 part 2)
1. **Batch jobs.** Add `POST /batch {tickers[], run, provider}` backed by a persistent queue (the
   `jobs` table plus a worker).
   - One job per run at a time.
   - Per-ticker progress.
   - A daily-limit stop shown as "paused until", not "failed".
2. **Caching.**
   - Cache LLM responses keyed by (prompt_hash, model, filing, field, chunk ids), so re-runs cost no
     tokens.
   - Cache BM25 indexes per filing.
   - Add cache headers on the summary endpoints.
3. **CI for Docker.** Build the image, start it, smoke-test `/runs` and `/`, and check that no `.env`
   or data files are in it.
4. **Smaller items:**
   - pagination on `/runs/{run}/filings`;
   - re-import when a run's jsonl changes;
   - optional auth if the service is ever exposed beyond localhost.
