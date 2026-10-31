# Next steps (updated 2026-10-31, Day 4)

## Done

- **Exact-match accuracy is the headline.** The old 0.5% figure is kept as `accuracy_tolerant`.
- **Dev results (gpt-oss-120b):**
  - `dev_gptoss_v1`: 81.8% exact.
  - After `finextract verify` (snap to source, offline): **93.2% exact, 0% ungrounded, 2.4%
    confident-wrong**.
- **Prompt versioning:**
  - `FINEXTRACT_PROMPT_VERSION` selects the wording: v1 is the default, v2 has cash excluding
    restricted cash.
  - Every run and row stores `prompt_version` and `prompt_hash`, and `--resume` refuses a mismatch.
  - Rows from before hashes existed count as v1 only if their run started before
    2026-10-31 18:21 +05:30.
  - The v1 hash is `5959365c4c18`.
- **Label QA:** 15 labels (10 dev, 5 test) checked against the filing text, 0 mismatches; marked
  `verified=yes` in `data/labels.csv`.
- **Test run:** `test5_gptoss_v1` has **33 of 50 fields** done (JNJ, WMT, HD complete; MCD 3/10;
  ORCL 0/10). Groq's daily token limit stopped it cleanly at 19:15. The retry-after of 997 s suggests the
  quota refills gradually at about 8k tokens/hour. The remaining 17 fields need ~42k tokens, so run it
  any time after ~5 hours, for example tomorrow.
- **Repo:** https://github.com/rmr2024/finextract (MIT; author is the noreply address). The test5
  predictions file and `logs/` are gitignored.

## Tomorrow: the one command

Run this in a new PowerShell window in the project folder. It loads the Groq key from .env without
printing it and resumes test5 with prompt v1.

```powershell
$k = (Get-Content .env | Where-Object { $_ -match '^\s*GROQ_API_KEY\s*=' } | Select-Object -First 1) -replace '^\s*GROQ_API_KEY\s*=\s*','' ; $env:OPENAI_API_KEY = $k.Trim().Trim('"'); $env:OPENAI_BASE_URL = "https://api.groq.com/openai/v1"; $env:FINEXTRACT_MIN_INTERVAL = "25"; $env:FINEXTRACT_REASONING_EFFORT = "low"; $env:FINEXTRACT_PROMPT_VERSION = "v1"; .\.venv\Scripts\Activate.ps1; finextract extract --provider openai --model openai/gpt-oss-120b --tickers JNJ WMT HD MCD ORCL --workers 1 --k 4 --resume --run test5_gptoss_v1 *>> logs\groq_test5.log
```

## Then (only once all 50 fields are done)

1. `finextract evaluate --run test5_gptoss_v1`
2. `finextract verify --run test5_gptoss_v1`, using the frozen rules with no changes for test, then
   `finextract evaluate --run test5_gptoss_v1_verified`.
3. Compare aggregates on the same 5 tickers: heuristic v2 (`test_heuristic_v2`, filtered to JNJ WMT HD
   MCD ORCL) vs gpt-oss v1 vs gpt-oss v1 + verify. Report exact, tolerant, coverage, ungrounded and
   confident-wrong. Explain any dev vs test gap. Don't inspect individual test errors.
4. Commit the test5 results once complete: remove the `data/predictions/test5_*` line from
   .gitignore, or add the files with `git add -f`.

## Later

- `dev_gptoss_v2` (prompt v2) to check whether the cash wording fixes CAT cash without side effects
  (~125k tokens, one day of quota).
- Retrieval: the 2 dev misses (MSFT total liabilities, NKE total assets) never reach the model. Raise k,
  or boost balance-sheet and cash-flow headings.
- Label QA: check more labels to tighten the bound (0/15 gives a one-sided 95% upper bound of ~18%).

## Ollama timings (reference; `--limit 1`, AAPL, `--k 4`, CPU only)

| Model | sec/field | JSON parse |
|---|---|---|
| qwen3.5:9b-q4_K_M | 117.1 (3 timeouts at the old 120 s limit) | 7/10 |
| gemma4:e4b-it-q4_K_M | 83.3 | 10/10 |
