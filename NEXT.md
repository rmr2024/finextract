# Next steps (updated 2026-10-31)

## Current state

- Dev set (AAPL MSFT KO NKE CAT) and held-out test set (15 tickers) are in `config.py`.
- Heuristic v2: dev accuracy 68.2%, test accuracy 55.5%.
- **LLM backend is now Groq's free tier** (`openai/gpt-oss-120b`), not local Ollama. Ollama on this CPU
  ran at 83-117 s/field (timings kept below).
- Dev run `dev_gptoss_v1` is done:
  - accuracy 88.6% (81.8% exact-match), coverage 95.5%;
  - ungrounded 14.3% (6/42), confident-wrong 7.1%;
  - 24.0 s/field, set by the throttle;
  - 121k tokens in / 6k out. See README "LLM results (dev)".
- Rate-limit handling:
  - `FINEXTRACT_MIN_INTERVAL` sets the gap between requests.
  - A 429 waits out its Retry-After.
  - A per-day limit, or a wait longer than `FINEXTRACT_MAX_WAIT` (600 s), stops the run cleanly.
  - `--resume` skips fields already done and retries failed ones.
- Groq needs `reasoning_effort=low`. At the default (medium), reasoning used up the 300-token output
  budget and Groq returned 400 `json_validate_failed`. That error now counts as a parse error for that
  field and no longer turns off JSON mode.

## Groq setup (key stays in .env, which is gitignored; never print it)

The helper script loads only GROQ_API_KEY from .env into the process, without printing it. In a
fresh shell, do the same yourself, then:

```powershell
$env:OPENAI_API_KEY = $env:GROQ_API_KEY
$env:OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
$env:FINEXTRACT_MIN_INTERVAL = "25"
$env:FINEXTRACT_REASONING_EFFORT = "low"
```

Free-tier limits: ~30 req/min, 8k tokens/min, 200k tokens/day. One field costs ~2.5k tokens, so
5 filings (50 fields) is ~125k tokens.

## Next run: test5 subset with gpt-oss

Today used ~122k of the 200k daily tokens, so the test5 run will probably hit the cap partway. That is
fine: it stops cleanly, and the same command with `--resume` continues it the next day.

```powershell
finextract extract --provider openai --model openai/gpt-oss-120b --tickers JNJ WMT HD MCD ORCL --workers 1 --k 4 --resume --run test5_gptoss_v1 *>> logs\groq.log
finextract evaluate --run test5_gptoss_v1
```

Compare against `test_heuristic_v2`, filtered to the same 5 tickers. Report aggregate metrics only;
test-set errors are not inspected while tuning.

## Stage 2 candidates (from the dev errors)

1. **Copy the number from the verified quote.** 5 of 6 ungrounded answers quote the right line but
   change a digit or drop decimals. Re-read the value deterministically from that line and column.
2. **Exact-match scoring.** The 0.5% tolerance counts 3 wrong values as correct. Make exact match the
   headline metric, or tighten the tolerance to rounding only.
3. **Concept check.** "Cash ... and restricted cash" was accepted as cash. Reject quote labels that
   don't fit the field (restricted, current portion, segment rows).

## Ollama timings (kept for reference; `--limit 1`, AAPL, `--k 4`, CPU only)

| Model | sec/field | JSON parse |
|---|---|---|
| qwen3.5:9b-q4_K_M | 117.1 (3 timeouts at the old 120 s limit) | 7/10 |
| gemma4:e4b-it-q4_K_M | 83.3 | 10/10 |
