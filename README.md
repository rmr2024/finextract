# finextract

**How often do LLMs invent numbers when reading SEC filings — and how do you stop it?**

`finextract` is a benchmark and pipeline for extracting key financial figures from 10-K
filings. It measures not just *accuracy* but *how* extraction fails: wrong scale, wrong
sign, last year's number, or a figure with no support in the source document.

Ground truth comes from each company's own XBRL tags, pulled from SEC EDGAR, so the
benchmark scales to hundreds of filings without hand-labeling every value.

> Status: **Stage 1 — baseline.** The pipeline runs end to end and is measured. The
> verification layer (Stage 2) comes next and is compared against these numbers.

---

## Pipeline

```
SEC EDGAR ──► 10-K HTML ──► clean text ──► chunks ──► BM25 retrieval ──► extractor ──► JSON + quote
     │                     (strip hidden iXBRL,        (per field)       (heuristic /
     │                      tables → rows)                                LLM)
     └──► XBRL company facts ──► labels.csv ──────────────────────────► evaluator ──► report
```

Every prediction stores the exact line the extractor says the number came from. The
evaluator checks that line against the filing. If the quote isn't in the document, or
doesn't contain the number, the answer is **ungrounded**: the measurable form of a
hallucination.

## Fields

Revenue, operating income, net income, diluted EPS, total assets, total liabilities,
stockholders' equity, cash & equivalents, long-term debt, operating cash flow.
(Edit `src/finextract/config.py` to add more.)

## Quick start

```bash
pip install -e ".[dev]"
pytest                       # 25 tests, runs offline
finextract demo              # full pipeline on a bundled synthetic filing, no keys needed
```

## Running the real benchmark

```bash
# 1. SEC requires a contact in the User-Agent
export SEC_USER_AGENT="Your Name your@email.com"

# 2. Download the latest 10-K for 30 large companies (edit the list in config.py)
finextract download                         # or: --tickers AAPL MSFT JPM GS --per-company 2

# 3. Build ground-truth labels from XBRL
finextract label                            # writes data/labels.csv

# 4. Run extractors
finextract extract --provider heuristic --run baseline_heuristic

export ANTHROPIC_API_KEY=...
finextract extract --provider anthropic --model claude-haiku-5-5 --run baseline_haiku --limit 3   # cheap test first

# Free, local option via Ollama (any OpenAI-compatible server works)
export OPENAI_BASE_URL=http://localhost:11434/v1
finextract extract --provider openai --model llama3.1 --run baseline_llama

# 5. Score
finextract evaluate --run baseline_haiku    # writes reports/baseline_haiku.md and _items.csv
```

## Metrics

| Metric | Meaning |
|---|---|
| Accuracy | exact matches (after applying scale) ÷ labeled fields. The headline metric |
| Accuracy (within 0.5%) | `accuracy_tolerant`: the old headline. It counts one-digit slips like 20,835 vs 20,935 as right |
| Coverage | share of fields where the extractor gave an answer |
| Ungrounded | answers whose quote isn't in the filing, or doesn't contain the number |
| Confident-wrong | answered but not an exact match. Worse than "not found" in a financial workflow |

Every error is classified as `near_miss` (within 0.5% but not exact), `scale_error`, `sign_error`,
`wrong_period` (returned the prior year's comparative figure), or `wrong_other`. That breakdown tells you *what to fix*.

## Labels: what to verify by hand

XBRL values are the filer's own tags, not an independent audit. Tag choice varies (e.g.
which "revenue" tag a company uses), and some values are restated later. Before trusting
results, spot-check about 10% of `data/labels.csv` against the filings:

- Correct → set `verified` to `yes`
- Wrong → set `verified` to `fixed:<correct value>` (the evaluator uses your value)
- Note anything odd in `notes`

## Findings so far

- **Scale propagation was the largest single fixable error.** The "(In millions)" header often
  lands in a different chunk from its table rows, so the extractor returned 442,387 instead of
  442,387,000,000. `chunk_text` now carries the most recent scale hint forward as a
  `[amounts in <scale>]` line. This removed all scale errors (dev 3 to 0, test 14 to 0) and
  broke no previously correct item. LLM extractors read the same chunks, so they benefit too.
- **The heuristic's 0% ungrounded is by design, not a finding.** It only returns a number copied
  from a real line of the filing, so its quote is always found. Real hallucination rates
  come from the LLM runs.
- **The LLM's ungrounded answers are copy errors, not invented lines.** gpt-oss-120b quoted a
  real line (or a near-copy of one) every time, but it changed one digit when writing out the
  value (20,935 to 20,835; 67,589 to 67,189) or dropped decimals (18.81 to 18). The grounding
  check flagged all 6, including every confident-wrong answer.
- **The evaluator's 0.5% tolerance hid some wrong values.** Two of those digit slips and one
  wrong-concept answer (cash *including restricted cash*, 9,986 vs 9,980) were within 0.5%, so
  they counted as "correct". Accuracy is now exact match after scale (`near_miss` is its own
  class), and the tolerant figure is kept as `accuracy_tolerant`.
- **Snapping each answer to its source line fixes the copy errors without another LLM call.**
  Re-reading the number from the real filing line raised gpt-oss dev exact accuracy from 81.8% to
  93.2% and cut ungrounded answers from 14.3% to 0%, without breaking any correct value.

## Baseline results

`finextract extract --provider heuristic --run baseline_heuristic` on the latest 10-K of
AAPL, MSFT, KO, NKE, CAT (10 fields each, 44 with XBRL labels; BM25 top-6 chunks).

| Metric | Value |
|---|---|
| Labeled fields | 44 |
| Accuracy | 61.4% (27/44) |
| Coverage (answered) | 77.3% (34/44) |
| Ungrounded answers | 0.0% |
| Confident-wrong answers | 20.6% (7/34) |

The 0% ungrounded is structural (the heuristic copies real lines). The baseline's real
problems are wrong and missing answers.

Root causes of the 17 non-correct items (each checked against `data/text`):

| Cause | Count | Items |
|---|---|---|
| Alias gap: the filing uses a line-item name the heuristic doesn't know | 8 | KO revenue ("Net operating revenues"), KO equity ("Equity attributable to shareowners"), NKE cash ("Cash and equivalents"), NKE + MSFT + CAT operating cash flow, CAT operating income ("Operating profit"), CAT diluted EPS |
| Wrong line: prefix/first-match takes the current portion, a segment, or a sub-line | 4 | AAPL + CAT long-term debt (current portion), CAT revenue ("Revenues of Financial Products"), KO operating income (first segment column) |
| Scale lost: the "(In millions)" header sits in a different chunk from the row (fixed in v2) | 3 | MSFT equity, KO net income, CAT cash |
| Retrieval miss: the correct line exists but isn't in the top-6 chunks | 2 | MSFT total liabilities, NKE total assets |

Examples:

- **Scale lost (MSFT equity):** the quote is `Total stockholders' equity | 442,387 | ...`, so the
  extractor returns 442,387 instead of 442,387,000,000, because the chunk holding that row
  has no "(In millions)" hint.
- **Wrong line (CAT long-term debt):** the alias `long-term debt` prefix-matches
  `Long-term debt due within one year | 7,120`, which comes before the correct
  `Long-term debt due after one year | 30,696`.

### Dev / test results (heuristic)

Dev = AAPL MSFT KO NKE CAT (used for tuning). Test = JNJ PFE WMT COST HD PEP PG MCD DIS NFLX INTC
CSCO ORCL IBM UPS (held out: aggregate metrics only, errors never inspected while tuning).
Sets are in `config.DEV_TICKERS` / `config.TEST_TICKERS`. v1 = baseline, v2 = scale propagation.

| Set | Run | Labeled | Accuracy | Coverage | Confident-wrong | Scale errors |
|---|---|---|---|---|---|---|
| Dev | v1 `baseline_heuristic` | 44 | 61.4% | 77.3% | 20.6% | 3 |
| Dev | v2 `dev_heuristic_v2` | 44 | 68.2% | 77.3% | 11.8% | 0 |
| Test | v1 `test_heuristic_v1` | 137 | 46.0% | 75.9% | 39.4% | 14 |
| Test | v2 `test_heuristic_v2` | 137 | 54.7% | 75.9% | 27.9% | 0 |

Accuracy is exact match. Within 0.5%, test v2 is 55.5%, which was the old headline; all other rows are
the same either way. Ungrounded is 0.0% in every heuristic run, by construction.

### LLM results (dev)

`openai/gpt-oss-120b` on Groq's free tier (`--provider openai --workers 1 --k 4`, JSON mode,
`reasoning_effort=low`, `FINEXTRACT_MIN_INTERVAL=25`). Run `dev_gptoss_v1`: 121,169 tokens in and
6,122 out for 50 fields, with 100% JSON parse and 0 errors.

| Dev (44 labeled) | Accuracy (exact) | Within 0.5% | Coverage | Ungrounded | Confident-wrong | s/field |
|---|---|---|---|---|---|---|
| Heuristic v2 | 68.2% | 68.2% | 77.3% | 0.0% (by design) | 11.8% | 0.0 |
| gpt-oss-120b v1 | 81.8% | 88.6% | 95.5% | 14.3% (6/42) | 14.3% (6/42) | 24.0* |
| gpt-oss-120b v1 + snap to source | **93.2%** | 95.5% | 95.5% | 0.0% | 2.4% (1/42) | 24.0* (+0.1 offline) |

\* Set by the 25 s free-tier throttle, not by model speed.

The 6 ungrounded answers (each one checked against `data/text`):

| Item | Model value | Model quote | Real line | Cause |
|---|---|---|---|---|
| MSFT cash | 20,835 | `Cash and cash equivalents \| 20,935` | `Cash and cash equivalents \| 20,935 \| 30,242` | Right line, one digit changed in the value (`near_miss`) |
| MSFT long-term debt | 31,167 | `Long-term debt \| 31,067 \| 40,152` | same | Right line, one digit changed (`near_miss`) |
| NKE equity | 14,865 | `Total shareholders' equity \| 14,965 \| 13,213` | `... \| 14,865 \| 13,213` | Value right, digit changed in the *quote* (quote not found) |
| CAT revenue | 67,189 | `Total sales and revenues \| 67,589 \| ...` | same | Right line, one digit changed (0.6% off, wrong) |
| CAT diluted EPS | 18 | `Profit per common share - diluted 2 \| 18.81 \| ...` | same | Decimals dropped |
| CAT total liabilities | 77,767 | `Total liabilities \| 77,267 \| 68,270` | same | Right line, one digit changed (wrong) |

Other errors: 2 missing (MSFT total liabilities and NKE total assets, the same 2 rows retrieval
missed for the heuristic), plus CAT cash, a grounded wrong-concept answer (`near_miss`).

### Stage 2: snap to source (offline)

`finextract verify --run X` writes `X_verified`. It is post-processing only, with no LLM calls (~4 s
for 50 fields):

1. Fuzzy-match the model's quote to the closest real line in `data/text`, using the difflib ratio
   against the line cut to the quote's column count.
2. Require a ratio of at least 0.85 and the same row label. Otherwise the answer is unverified and
   its value is set to `None`.
3. From that line, take the column whose digits differ least from the model's number (numeric
   distance breaks ties), then apply the scale.
4. Each row records `verified_line`, `match_ratio` and `value_changed`.

Dev results for `dev_gptoss_v1`, 7 values changed:

| Item | Before | After | Result |
|---|---|---|---|
| MSFT cash | 20,835 | 20,935 | near_miss -> correct |
| MSFT long-term debt | 31,167 | 31,067 | near_miss -> correct |
| CAT revenue | 67,189 | 67,589 | wrong -> correct |
| CAT diluted EPS | 18 | 18.81 | wrong -> correct |
| CAT total liabilities | 77,767 | 77,267 | wrong -> correct |
| CAT net income | 8,822 | 8,882 | unlabeled (no XBRL label) |
| CAT equity | 21,118 | 21,318 | unlabeled |

Plus NKE operating income (unlabeled): its quote matched no line (ratio 0.74), so its value was set
to None. No correct value was broken.

Two rules were tightened after the first dev pass, which got 2 changes wrong:
- MSFT cash snapped to a shorter, different "Cash and cash equivalents | 12,976" row. That is why
  lines are now cut to the quote's column count before matching.
- CAT revenue snapped to the numerically nearer 2023 column. That is why columns are now chosen
  by digit distance.

Still wrong after verification: 2 missing (retrieval) and CAT cash (wrong concept, restricted cash
included). Snapping can only fix the number; it cannot fix the wrong line or a missing line.

**Field definition change (future runs only):** the `cash` description in `config.py` now says to
exclude restricted cash. The description is part of the prompt, so this changes only runs made after
2026-10-31. `dev_gptoss_v1` and `test5_gptoss_v1` were extracted with the old wording.

## Roadmap

- **Stage 2 — verification layer:** reject answers whose quote isn't in the source, check
  accounting identities (assets = liabilities + equity), carry table scale headers into
  every chunk, retry on failure. Report before/after.
- **Stage 3 — service:** FastAPI, async batch jobs, result store, dashboard showing each
  figure beside its source line, Docker.
- **Stage 4 — depth:** 10-Qs and credit agreements, multi-model cost/accuracy comparison,
  error analysis by sector and document length, publish the labeled dataset.

## Project layout

```
src/finextract/
  config.py     field definitions, XBRL tags, retrieval queries
  edgar.py      SEC client (rate-limited, cached)
  labels.py     ground truth from XBRL company facts
  textproc.py   HTML → text, table flattening, chunking
  retrieve.py   BM25 retriever (no dependencies)
  llm.py        heuristic / Anthropic / OpenAI-compatible extractors
  extract.py    pipeline + grounding evidence
  evaluate.py   metrics, error classes, reports
  sample/       synthetic 10-K + XBRL facts for tests and the demo
tests/          offline test suite
```

Data comes from SEC EDGAR, which is public. The bundled sample company is fictional.
