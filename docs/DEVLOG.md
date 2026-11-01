# Development log

Detailed results and decisions, stage by stage. The [README](../README.md) has the summary.

Sets: **dev** = AAPL MSFT KO NKE CAT (used for tuning). **test** = held out. The heuristic runs
used 15 test tickers. The LLM runs used 5 of them (JNJ WMT HD MCD ORCL) to fit a free API quota.
Each set has 44 labeled fields. Until v1.0, test errors were only looked at in aggregate. Once the test
set was final and nothing would be tuned again, its errors were inspected (see Stage 4).

---

## Stage 1: heuristic baseline

`finextract extract --provider heuristic` on the dev set: 10 fields each, 44 with XBRL labels,
BM25 top-6 chunks.

| Metric | Value |
|---|---|
| Accuracy | 61.4% (27/44) |
| Coverage | 77.3% (34/44) |
| Ungrounded | 0.0% (by construction: the heuristic only copies real lines) |
| Confident-wrong | 20.6% (7/34) |

Root causes of the 17 non-correct items, each checked against `data/text`:

| Cause | Count | Items |
|---|---|---|
| Alias gap: the filing uses a line-item name the heuristic doesn't know | 8 | KO revenue ("Net operating revenues"), KO equity, NKE cash ("Cash and equivalents"), NKE/MSFT/CAT operating cash flow, CAT operating income ("Operating profit"), CAT diluted EPS |
| Wrong line: prefix or first match picks the current portion, a segment or a sub-line | 4 | AAPL and CAT long-term debt, CAT revenue ("Revenues of Financial Products"), KO operating income |
| Scale lost: the "(In millions)" header is in a different chunk from the row | 3 | MSFT equity, KO net income, CAT cash |
| Retrieval miss: the right line isn't in the top-k chunks | 2 | MSFT total liabilities, NKE total assets |

**Windows encoding fix.** On Windows, Python's default text encoding is cp1252, so filings containing
"☒" crashed or garbled the text cache. Every read and write now passes `encoding="utf-8"`, the cache
is written atomically (temp file, then `os.replace`), an empty cache counts as missing, and a
regression test round-trips the character. The suite runs under
`-X warn_default_encoding -W error::EncodingWarning`.

## Stage 1.5: scale propagation

`chunk_text` now carries the most recent "(In thousands/millions/billions)" hint forward as an
`[amounts in <scale>]` line. That line is added only to chunks that have no hint of their own.

| Set | Run | Accuracy | Coverage | Confident-wrong | Scale errors |
|---|---|---|---|---|---|
| Dev | heuristic v1 | 61.4% | 77.3% | 20.6% | 3 |
| Dev | heuristic v2 | 68.2% | 77.3% | 11.8% | 0 |
| Test (15 tickers, 137 labeled) | heuristic v1 | 46.0% | 75.9% | 39.4% | 14 |
| Test (15 tickers, 137 labeled) | heuristic v2 | 54.7% | 75.9% | 27.9% | 0 |

No previously correct item broke on either set.

## Stage 2a: local LLMs (Ollama, CPU only)

Fixes needed before local models were usable:
- **Context check.** Ollama silently truncates prompts that exceed its context window. The context is
  raised to 8192, and a warning fires if a prompt (estimated at ~4 chars per token) exceeds it.
- **JSON mode.** Requests send `response_format=json_object`, falling back without it if the server
  rejects the parameter.
- **Thinking models.** Qwen 3.5 and Gemma 4 spent the whole 300-token output budget on hidden
  reasoning and returned empty content. `reasoning_effort=none` is sent to local servers.
- **Timeout.** The request timeout was raised from 120 s to 600 s (`FINEXTRACT_TIMEOUT`).

`--limit 1` timings (AAPL, `--k 4`):

| Model | sec/field | JSON parse |
|---|---|---|
| qwen3.5:9b-q4_K_M | 117.1 (3 timeouts at the old 120 s limit) | 7/10 |
| gemma4:e4b-it-q4_K_M | 83.3 | 10/10 |

At ~2 minutes per field on CPU, the full benchmark was impractical locally, so the LLM runs moved to a
hosted free tier.

## Stage 2b: gpt-oss-120b on Groq's free tier

Settings: `--provider openai --model openai/gpt-oss-120b --workers 1 --k 4`, JSON mode,
`reasoning_effort=low`. At the default reasoning effort, the output budget ran out mid-JSON and the
server returned `json_validate_failed`. That error now counts as a parse error for that field and
does not turn off JSON mode.

Rate-limit handling:
- `FINEXTRACT_MIN_INTERVAL=25` seconds between requests.
- A 429 waits out its `Retry-After`.
- A per-day limit, or a wait longer than `FINEXTRACT_MAX_WAIT`, stops the run cleanly.
- Rows are written as they finish, so `--resume` continues where the run stopped.

Dev run `dev_gptoss_v1`: 121,169 tokens in and 6,122 out for 50 fields; 100% JSON parse; 0 errors.

The 6 ungrounded dev answers were all copying errors on a real line:

| Item | Model value | Real value | Error |
|---|---|---|---|
| MSFT cash | 20,835 | 20,935 | one digit changed |
| MSFT long-term debt | 31,167 | 31,067 | one digit changed |
| NKE equity | 14,865 (right) | 14,865 | digit changed in the *quote* |
| CAT revenue | 67,189 | 67,589 | one digit changed |
| CAT diluted EPS | 18 | 18.81 | decimals dropped |
| CAT total liabilities | 77,767 | 77,267 | one digit changed |

**Metric change.** The original 0.5% tolerance counted 3 wrong values as correct: two digit slips, and
"cash, cash equivalents and restricted cash" (9,986) accepted for cash (9,980). Accuracy is now exact
match after scale. The tolerant figure is kept as `accuracy_tolerant`, and those cases get their own
class, `near_miss`.

## Stage 2c: snap-to-source verification (`finextract verify`)

Offline post-processing with no LLM calls, about 4 s for 50 fields:

1. Fuzzy-match the model's quote to the closest real line in the filing text, using the difflib ratio
   against each line cut to the quote's column count.
2. Require a ratio of at least 0.85 and the same row label; otherwise the value is set to `None`
   (unverified).
3. From that line, take the column whose digits differ least from the model's number; numeric
   distance breaks ties. Then apply the scale.
4. Each row records `verified_line`, `match_ratio` and `value_changed`.

Two rules were tightened after the first dev pass, which got 2 of its 7 changes wrong:
- MSFT cash snapped to a shorter, different "Cash and cash equivalents | 12,976" row. Lines are now
  cut to the quote's column count before matching.
- CAT revenue snapped to the numerically nearer 2023 column. Columns are now chosen by digit
  distance first.

Dev result: 5 labeled values became correct and none were broken. Exact accuracy went from 81.8% to
93.2%, and ungrounded from 14.3% to 0%. Still wrong after verify: 2 missing (retrieval) and CAT cash
(the wrong line item, so snapping cannot help).

**Prompt versioning.** Field descriptions are part of the prompt. `FINEXTRACT_PROMPT_VERSION` selects
the wording: v1 is the default; v2 makes `cash` exclude restricted cash. Every run and row stores
`prompt_version` and `prompt_hash`, and `--resume` refuses to mix them. Both LLM runs are v1, hash
`5959365c4c18`. v2 has not been run.

**Label QA.** 15 labels (10 dev, 5 test) were checked against the filing text before any predictions
were inspected. 0 mismatched, which gives a one-sided 95% upper bound of about 18% on the label error
rate. Stage 4 found one label outside that sample with a definition mismatch (HD, below).

## Stage 3: service

- A SQLite store (`data/finextract.db`), loaded with `finextract import --run X`.
- A FastAPI app with read endpoints, plus `POST /extract` as a background job.
- A one-page dashboard. `finextract serve` binds 127.0.0.1.
- A Dockerfile; the image isn't built in CI yet.

Details are in the README.

Operational note: on the development machine, runs launched with `Start-Process` from an automation
shell were killed twice. Runs launched as a tracked background job, or from a normal terminal,
finished normally.

## Stage 4: held-out test results and error breakdown

`test5_gptoss_v1`: same settings and prompt as dev. It finished 50/50 after two clean stops at the
daily token limit. `verify` used the dev-frozen rules, unchanged.

| Run | Set | Exact | Within 0.5% | Coverage | Ungrounded | Confident-wrong |
|---|---|---|---|---|---|---|
| Heuristic v2 | dev | 68.2% | 68.2% | 77.3% | 0.0% | 11.8% |
| gpt-oss v1 | dev | 81.8% | 88.6% | 95.5% | 14.3% | 14.3% |
| gpt-oss v1 + verify | dev | 93.2% | 95.5% | 95.5% | 0.0% | 2.4% |
| Heuristic v2 | test | 59.1% | 59.1% | 84.1% | 0.0% | 29.7% |
| gpt-oss v1 | test | 75.0% | 75.0% | 95.5% | 14.3% | 21.4% |
| gpt-oss v1 + verify | test | **84.1%** | 84.1% | 95.5% | 0.0% | 11.9% |

**Test breakdown** (labeled fields; inspected after the test set was frozen):

- **6 ungrounded before verify** (of 42 answered): 5 digit slips and 1 dropped-decimal answer.
- **4 made correct by verify:**
  - HD equity: 12,613 → 12,813
  - JNJ cash: 19,109 → 19,709
  - ORCL net income: 17,187 → 17,087
  - ORCL operating cash flow: 31,177 → 31,977
- **2 ungrounded but not fixed:**
  - ORCL equity: the digit was restored (43,156 → 43,056), but the line is "Total stockholders'
    equity", including noncontrolling interests. The label is the Oracle-only line, 42,508. That's a
    wrong line item.
  - WMT diluted EPS: the model answered "2" for 2.73. With the decimals dropped, every column ties on
    digit distance, and the numeric tiebreak chose the prior year's 2.41. That's a snap-rule failure;
    it changed the class from wrong to wrong_period, and the answer is still wrong.
- **3 grounded but wrong all along** (verify cannot change these):
  - WMT net income: "Consolidated net income" 22,270, versus attributable to Walmart 21,893.
  - WMT equity: "Total shareholders' equity" 105,887, versus Walmart shareholders' 99,617.
  - HD long-term debt: 46,341, discussed below.
- **5 grounded-but-wrong after verify:** ORCL equity, WMT EPS, WMT net income, WMT equity and HD
  long-term debt. Confident-wrong is 5/42 = 11.9%.
- **2 missing:** HD operating cash flow and ORCL total assets (no answer was returned).

**HD long-term debt is a label issue, not a model error.** The field is defined as the non-current
portion, and HD's balance sheet shows "Long-term debt, excluding current installments | 46,341", which
is the model's answer. HD has no `LongTermDebtNoncurrent` fact, so the label fell back to
`LongTermDebt` = 49,397, the debt-maturity schedule total. The label was left unchanged so the
headline isn't adjusted after the fact. With it corrected, gpt-oss + verify on test would be 86.4%
exact.

**Dev vs test gap:**
- **Test filings are harder.** The never-tuned heuristic also drops 9.1 points.
- **The error mix differs.** Dev's errors were mostly copying slips, which verify fixes. Test's 9 wrong
  answers (33 correct + 9 wrong + 2 missing = 44) break down as:
  - 5 copying errors on the right line: 4 digit slips and 1 dropped-decimal answer;
  - 1 copying error on the wrong line: ORCL equity;
  - 2 wrong line items: WMT net income and WMT equity, where the model took the consolidated figure
    instead of the one attributable to the parent;
  - 1 label mismatch: HD.

  Verify fixed 4 of the 5 right-line copying errors. WMT EPS was the one it missed.
- **Dev is partly fit.** The two snap rules were tuned on dev.
- **n=44 is small.** One field is about 2.3 points, and the 95% interval is roughly ±11 points.

**Unmatched quotes.** Across all 90 gpt-oss answers (dev and test), exactly 1 quote matched no filing
line. For NKE operating income, which Nike doesn't report as a line and which has no XBRL label, the
model subtracted selling and administrative expense from gross profit (3,797). It quoted the two real
lines joined with "...". Verify found no line with a ratio of at least 0.85 and set the value to
`None`. This is the only answer where the model produced a number that appears on no single line.
