# LLMs don't invent the numbers in 10-Ks; they miscopy them

## The problem

Ask a large language model to pull "total liabilities" out of a 300-page annual report and it will
usually give you a number. The question is whether that number is right, and when it isn't, *why*
not. "The model hallucinates" is not specific enough to fix. I wanted to measure the failure modes
precisely, then check whether a cheap, deterministic step could remove them.

## Ground truth for free

US public companies tag the numbers in their financial statements with XBRL, and the SEC publishes
every tagged value. For ten common fields (revenue, operating income, net income, diluted EPS, total
assets, total liabilities, equity, cash, long-term debt, operating cash flow), each 10-K comes with a
machine-readable answer key. That makes it possible to score extraction against thousands of numbers
without hand-labeling them.

That's also the main caveat: these particular fields don't *need* an LLM, because XBRL already has
them. The point is to benchmark the extraction method on documents where the answer is known, before
using it on documents where it isn't.

## The pipeline

1. **Download** each 10-K and its XBRL facts from SEC EDGAR. The client is rate-limited and cached.
2. **Flatten** the HTML to text, removing hidden XBRL markup and writing each table row as one line
   (`Total liabilities | 285,508 | 308,030`).
3. **Retrieve** the most relevant chunks for each field with BM25.
4. **Extract** with either a regex heuristic or an LLM. The LLM must return the value, its scale
   (millions, thousands) and the exact line it copied it from.
5. **Score** with exact match after scale. Every miss gets a class: wrong scale, wrong sign, prior
   year, near miss, missing, or simply wrong.

I kept two sets of five companies apart. A **dev** set was used for every decision. A **test** set was
held out until the method was frozen; before that, I looked only at its aggregate scores.

## What went wrong first

The heuristic baseline exposed a plumbing bug before any model was involved. A table's "(In
millions)" header often ends up in a different text chunk from the rows below it, so 442,387 million
was read as 442,387. Carrying the most recent scale hint into every chunk removed all 17 scale errors
across dev and test, and broke nothing. Every extractor benefits, because they all read the same
chunks.

A second surprise came from the metric itself. I had started with a 0.5% tolerance to absorb rounding,
but it was quietly counting wrong answers as right: 20,835 against a true 20,935 is only 0.48% off.
The headline metric became exact match, with the tolerant figure kept alongside.

## The finding

I ran `gpt-oss-120b` (via a free hosted API) over both sets. Every answer comes with a quote, so I
could check each one against the filing. Of 90 answers, 89 quoted a real line or a near-copy of one.
The errors were overwhelmingly **copying** errors:

- `Cash and cash equivalents | 20,935` quoted, **20,835** answered
- `Total sales and revenues | 67,589` quoted, **67,189** answered
- `Profit per common share, diluted | 18.81` quoted, **18** answered

The model found the right line, then changed one digit or dropped the decimals when writing the
number out. 11 of its 15 wrong answers across both sets look like this. The other 4: three real but
wrong line items (consolidated net income instead of income attributable to the parent) and one
label problem.

## The fix: snap to source

If the model has found the right line, the number is already sitting in the document. `verify` is a
post-processing step with no model call:

1. Fuzzy-match the quote to the closest real line in the filing (similarity of at least 0.85 and the
   same row label).
2. On that line, take the column whose digits are closest to the model's answer. A one-digit slip is
   one edit away from the true value, even when a prior-year column is numerically closer.
3. If nothing matches, return no answer rather than a guess.

Two of these rules came from mistakes on the dev set. At first a short quote matched a different,
shorter row, and the closest-*value* rule picked a 2023 column. The fixes went in before the test set
was opened.

## Results

| | Dev exact | Test exact | Test confident-wrong |
|---|---|---|---|
| Heuristic | 68.2% | 59.1% | 29.7% |
| gpt-oss-120b | 81.8% | 75.0% | 21.4% |
| gpt-oss-120b + verify | 93.2% | **84.1%** | 11.9% |

On the held-out test set, verify turned 4 wrong answers into correct ones, broke none, and reduced
ungrounded answers from 14.3% to 0%. The gap between dev and test is real: the test filings were
harder for the heuristic too, and the dev rules were partly fit to dev. 84.1% is the number I'd quote.

## Limitations

- **The sample is small.** 44 labeled fields per set, so roughly ±11 points.
- **Zero ungrounded after verify is guaranteed by construction.** Every value is read from a real
  line. That makes answers traceable, not correct.
- **Confident-wrong is the risk that remains.** Verify can't tell that the model chose the right
  *kind* of line. "Consolidated net income" is a real line; it's just not the one that was asked for.
- **Labels can be wrong too.** One label used a fallback XBRL tag that doesn't match the field
  definition. I documented it rather than changing the headline after seeing the results.

## What I'd do next

- **Concept checks.** Reject a line whose label contradicts the field definition, such as
  "noncontrolling", "current portion" or "restricted". That targets the biggest remaining error.
- **Untagged documents.** Run the same method on earnings press releases and other documents without
  XBRL, where it actually saves work.
- **An open benchmark.** Publish the labeled set and the scoring harness so other extractors and
  models can be compared on exact match, coverage and confident-wrong rather than a single accuracy
  number.

The code, data and every run are in this repository. Each number above can be regenerated with
`finextract evaluate`.
