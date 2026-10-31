# Next steps (updated 2026-10-31, Day 3 part 2)

## Current state

- **Headline accuracy is now exact match after scale.** The old 0.5% figure is kept as
  `accuracy_tolerant`, and values within 0.5% that aren't exact are classed `near_miss`.
- **Dev results (44 labeled):**
  - heuristic v2: 68.2%;
  - gpt-oss-120b `dev_gptoss_v1`: 81.8% exact, 14.3% ungrounded;
  - the same run after `finextract verify` (snap to source, offline): **93.2% exact, 0% ungrounded,
    2.4% confident-wrong**, with no correct value broken.
- **Test set:** test5 run `test5_gptoss_v1` (JNJ WMT HD MCD ORCL) was started on 2026-10-31 in a
  separate window, logging to `logs/groq_test5.log`. It uses the same settings and prompt as dev; it
  started before the cash-description change. It will likely stop at the Groq daily token cap.
  Test errors have not been inspected.
- **Cash field:** its description now excludes restricted cash. This changes the prompt, so it only
  affects runs after 2026-10-31.

## Tomorrow

1. Continue the test run with the same command plus `--resume`. It skips finished fields. The prompt
   now has the new cash wording, so the rows from tomorrow differ from today's in that one field.
   Note this in the results, or re-run cash for all 5 test filings to keep the run consistent.
   ```powershell
   # GROQ_API_KEY loaded from .env into the shell (never printed); then:
   $env:OPENAI_API_KEY = $env:GROQ_API_KEY; $env:OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
   $env:FINEXTRACT_MIN_INTERVAL = "25"; $env:FINEXTRACT_REASONING_EFFORT = "low"
   finextract extract --provider openai --model openai/gpt-oss-120b --tickers JNJ WMT HD MCD ORCL --workers 1 --k 4 --resume --run test5_gptoss_v1 *>> logs\groq_test5.log
   ```
2. Once it's complete, apply the frozen Stage 2 to the test run, with no tuning on test:
   ```powershell
   finextract evaluate --run test5_gptoss_v1
   finextract verify --run test5_gptoss_v1
   finextract evaluate --run test5_gptoss_v1_verified
   ```
   Compare aggregates only against `test_heuristic_v2`, filtered to the same 5 tickers.
3. Optional: re-run dev with the new cash wording (`dev_gptoss_v2`, ~125k tokens, one day of quota)
   to measure whether it fixes CAT cash without breaking other filings.

## Stage 2 remaining errors (dev)

- **2 missing (MSFT total liabilities, NKE total assets):** retrieval didn't return the balance-sheet
  chunk. Next fix: retrieval (raise k, or boost balance-sheet and cash-flow headings).
- **CAT cash:** the wrong line item, "... and restricted cash". Snapping can't fix this. The prompt
  change above, or a label-based concept check, is the fix.

## Ollama timings (kept for reference; `--limit 1`, AAPL, `--k 4`, CPU only)

| Model | sec/field | JSON parse |
|---|---|---|
| qwen3.5:9b-q4_K_M | 117.1 (3 timeouts at the old 120 s limit) | 7/10 |
| gemma4:e4b-it-q4_K_M | 83.3 | 10/10 |
