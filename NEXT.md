# Next steps (written 2026-10-30)

## Current state

- Dev set (AAPL MSFT KO NKE CAT) and held-out test set (15 tickers) are in `config.py`.
- Heuristic v2 (with scale propagation): dev accuracy 68.2%, test accuracy 55.5%. See README.
- Ollama 0.40.13 is installed and `OLLAMA_CONTEXT_LENGTH=8192` is set with setx. `ollama ps` showed
  8192, running 100% on CPU (integrated Intel Arc GPU, 15.5 GB RAM).
- Models: `qwen3.5:9b-q4_K_M` and `gemma4:e4b-it-q4_K_M` (6.6 GB each).
- Fixes done in `llm.py`:
  - `response_format=json_object`, with a fallback if the server rejects it.
  - The context-overflow warning.
  - `reasoning_effort=none` for local servers. Without it, Qwen spent all 300 output tokens
    thinking and returned empty content.
  - The request timeout is now 600 s by default (`FINEXTRACT_TIMEOUT`); it used to be 120 s.
- No full LLM run yet.

## Limit-1 timings (dev, AAPL only, 10 fields, `--workers 1 --k 4`)

| Model | sec/field | JSON parse | Errors | Tokens in / out | Context warnings |
|---|---|---|---|---|---|
| qwen3.5:9b-q4_K_M | 117.1* | 7/10 | 3 timeouts (old 120 s limit) | 20,048 / 366 | 0 |
| gemma4:e4b-it-q4_K_M | 83.3 | 10/10 | 0 | 28,952 / 479 | 0 |

\* This is a lower bound: 3 requests were cut off at 120 s.

Nearly all the time goes to reading the ~2-3k-token prompt on CPU; output is ~40 tokens per field.

## Options (hour estimates from the timings above, ~50 fields per 5 filings)

| # | Option | Estimate |
|---|---|---|
| 1 | Original plan, timeout 600: dev for both models, then all 15 test tickers with the better model | ~6.3 h (Qwen dev 1.6 + Gemma dev 1.2 + test 3.5) |
| 2 | Same as 1 but `--k 2` (about half the prompt) | ~3-4 h (untested guess, may lose recall) |
| 3 | Gemma as main, skip Qwen dev, all 15 test tickers | ~4.7 h |
| 4 | 5-ticker test subset instead of 15 | test part ~1.2 h instead of 3.5 h |

## Chosen plan for tomorrow (~2.3 h)

Gemma is the faster model, so it is the main one. Use `--k 4`, timeout 600, full dev, then a 5-ticker
test subset of test-set tickers only: JNJ WMT HD MCD ORCL.

```powershell
.\.venv\Scripts\Activate.ps1
$env:OPENAI_BASE_URL="http://localhost:11434/v1"; $env:OLLAMA_CONTEXT_LENGTH="8192"; $env:FINEXTRACT_TIMEOUT="600"
# make sure the Ollama tray app is running; `ollama ps` should show CONTEXT 8192 once a model loads
finextract extract --provider openai --model gemma4:e4b-it-q4_K_M --tickers AAPL MSFT KO NKE CAT --workers 1 --k 4 --run dev_gemma_v1
finextract evaluate --run dev_gemma_v1
finextract extract --provider openai --model gemma4:e4b-it-q4_K_M --tickers JNJ WMT HD MCD ORCL --workers 1 --k 4 --run test5_gemma_v1
finextract evaluate --run test5_gemma_v1
```

Optional, if time allows: Qwen full dev (`dev_qwen_v1`, ~1.6 h or more) for the model comparison.

After the runs:
- Compare against heuristic v2 on the same filings. `test_heuristic_v2` covers all 15 test tickers,
  so filter it to the 5 subset tickers.
- Report accuracy, coverage, ungrounded, confident-wrong and sec/field.
- List every ungrounded answer: model quote vs the real line, with a one-line cause.
- Update the README results, run strict pytest, commit "LLM baseline results". No push.
