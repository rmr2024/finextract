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
| Accuracy | correct ÷ labeled fields (0.5% relative tolerance) |
| Coverage | share of fields where the extractor gave an answer |
| Ungrounded | answers whose quote isn't in the filing, or doesn't contain the number |
| Confident-wrong | answered but wrong. Worse than "not found" in a financial workflow |

Every error is classified as `scale_error`, `sign_error`, `wrong_period` (returned the
prior year's comparative figure), or `wrong_other`. That breakdown tells you *what to fix*.

## Labels: what to verify by hand

XBRL values are the filer's own tags, not an independent audit. Tag choice varies (e.g.
which "revenue" tag a company uses), and some values are restated later. Before trusting
results, spot-check about 10% of `data/labels.csv` against the filings:

- Correct → set `verified` to `yes`
- Wrong → set `verified` to `fixed:<correct value>` (the evaluator uses your value)
- Note anything odd in `notes`

## Findings so far

- **Scale propagation is a real failure mode.** In the synthetic sample, the cash-flow
  table's "(In millions)" header lands in a different chunk from the table rows, so the
  extractor returns 2,903 instead of 2,903,000,000. The evaluator classifies it as a
  `scale_error`. LLM extractors see the same chunk boundaries, so measure how often this
  happens on real filings.

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

Root causes of the 17 non-correct items (each checked against `data/text`):

| Cause | Count | Items |
|---|---|---|
| Alias gap: the filing uses a line-item name the heuristic doesn't know | 8 | KO revenue ("Net operating revenues"), KO equity ("Equity attributable to shareowners"), NKE cash ("Cash and equivalents"), NKE + MSFT + CAT operating cash flow, CAT operating income ("Operating profit"), CAT diluted EPS |
| Wrong line: prefix/first-match takes the current portion, a segment, or a sub-line | 4 | AAPL + CAT long-term debt (current portion), CAT revenue ("Revenues of Financial Products"), KO operating income (first segment column) |
| Scale lost: the "(In millions)" header sits in a different chunk from the row | 3 | MSFT equity, KO net income, CAT cash |
| Retrieval miss: the correct line exists but isn't in the top-6 chunks | 2 | MSFT total liabilities, NKE total assets |

Examples:

- **Scale lost (MSFT equity):** the quote is `Total stockholders' equity | 442,387 | ...`, so the
  extractor returns 442,387 instead of 442,387,000,000, because the chunk holding that row
  has no "(In millions)" hint.
- **Wrong line (CAT long-term debt):** the alias `long-term debt` prefix-matches
  `Long-term debt due within one year | 7,120`, which comes before the correct
  `Long-term debt due after one year | 30,696`.

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
