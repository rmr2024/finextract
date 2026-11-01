# Contributing

## Setup

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev,api]"
```

## Tests

```bash
pytest -q
python -X warn_default_encoding -W error::EncodingWarning -m pytest -q   # strict: fails on any implicit text encoding
finextract demo                                                          # end-to-end smoke test, offline
```

Tests must run offline: no SEC downloads and no LLM calls. Use the bundled sample filing in
`src/finextract/sample/`, and fake providers or fake HTTP responses (see `tests/test_pipeline.py`).
Always pass `encoding="utf-8"` when reading or writing text files.

## Pull requests

- Keep each PR to one change, with a test that fails without it.
- If a change affects results, report before and after on the **dev** set (`finextract evaluate`):
  exact accuracy, coverage, ungrounded and confident-wrong. Don't tune on the test set.
- If a change alters the LLM prompt (template or field descriptions), add a new prompt version in
  `config.PROMPT_VERSIONS` instead of editing an existing one.
- Never commit secrets or `.env`. Downloaded filings (`data/raw`, `data/cache`, `data/text`) stay out
  of git.
- SEC access goes only through `edgar.py`. Keep its rate limit and User-Agent.
