import csv
import json
from pathlib import Path

import pytest

from finextract.config import FIELDS_BY_NAME
from finextract.evaluate import classify
from finextract.extract import extract_filing, grounding, run_extraction
from finextract.labels import label_filing
from finextract.llm import HeuristicProvider, OpenAICompatProvider, parse_json_response
from finextract.numbers import apply_scale, detect_scale, normalize_ws, parse_number
from finextract.retrieve import BM25
from finextract.textproc import chunk_text, html_to_text, load_filing_text

SAMPLE = Path(__file__).resolve().parents[1] / "src" / "finextract" / "sample"
ACCN = "0000000001-26-000001"


@pytest.fixture(scope="module")
def text():
    return html_to_text((SAMPLE / "sample_10k.html").read_bytes())


@pytest.fixture(scope="module")
def facts():
    return json.loads((SAMPLE / "sample_companyfacts.json").read_text(encoding="utf-8"))


# --- numbers -------------------------------------------------------------
@pytest.mark.parametrize("s,expected", [
    ("12,412", 12412), ("$ 3.21", 3.21), ("(1,880)", -1880), ("(45", None), ("—", None),
    ("-7", -7), (2903, 2903), (None, None),
])
def test_parse_number(s, expected):
    # "(45" without a closing paren is ambiguous, but must not crash
    if s == "(45":
        assert parse_number(s) == 45
    else:
        assert parse_number(s) == expected


def test_scale():
    assert detect_scale("(In millions, except per share amounts)") == "millions"
    assert detect_scale("no hint here") == "units"
    assert apply_scale(2.5, "billions") == 2.5e9


# --- text processing -----------------------------------------------------
def test_hidden_ixbrl_removed(text):
    assert "99,999" not in text


def test_table_rows_and_paren_merge(text):
    assert "Revenues | 12,412 | 11,493" in text
    assert "Other income (expense), net | (45) | 12" in text


def test_chunks_never_split_lines(text):
    chunks = chunk_text(text, max_chars=400, overlap_lines=1)
    lines = set(text.splitlines())
    for c in chunks:
        for line in c.splitlines():
            if line.startswith("[amounts in "):  # synthetic scale tag, see chunk_text
                continue
            assert line in lines


# --- retrieval -----------------------------------------------------------
def test_bm25_finds_balance_sheet(text):
    chunks = chunk_text(text, max_chars=600)
    top = BM25(chunks).search(FIELDS_BY_NAME["total_assets"].query, k=2)
    assert any("Total assets" in chunks[i] for i in top)


# --- labels --------------------------------------------------------------
def test_labels_current_and_prior(facts):
    lab = label_filing(facts, ACCN)
    assert lab["revenue"]["value"] == 12412000000
    assert lab["revenue"]["prior_value"] == 11493000000
    # falls back to the second-priority revenue tag
    assert lab["revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert lab["eps_diluted"]["value"] == 3.21
    assert lab["stockholders_equity"]["prior_value"] == 11232000000


def test_labels_ignore_quarter_and_other_filings(facts):
    lab = label_filing(facts, ACCN)
    assert lab["revenue"]["value"] != 3301000000          # Q4-only figure excluded
    assert label_filing(facts, "9999999999-99-999999")["revenue"] is None


# --- evaluation ----------------------------------------------------------
@pytest.mark.parametrize("pred,cls", [
    (12412e6, "correct"), (12412, "scale_error"), (-12412e6, "sign_error"),
    (11493e6, "wrong_period"), (5e9, "wrong_other"), (None, "missing"),
])
def test_classify(pred, cls):
    assert classify(pred, {"value": 12412e6, "prior_value": 11493e6}) == cls


def test_grounding_flags_invented_quote(text):
    norm = normalize_ws(text)
    assert grounding("12412", "Revenues | 12,412 | 11,493", norm) == (True, True)
    assert grounding("13000", "Revenues | 12,412 | 11,493", norm) == (True, False)   # number not in quote
    assert grounding("12412", "Total revenue was 12,412", norm) == (False, True)     # quote not in filing


# --- providers & pipeline ------------------------------------------------
def test_parse_json_response():
    out = parse_json_response('Sure!\n{"value": 2148, "scale": "millions", "quote": "Operating income | 2,148"}')
    assert out["value"] == 2148 and out["scale"] == "millions"
    assert parse_json_response("no json")["parse_error"]


class FabricatingProvider:
    """Simulates an LLM that confidently invents a number and a quote."""
    name = "fake"

    def extract(self, field, company, period, chunks):
        return {"value": "999", "scale": "millions", "quote": "Totally real line | 999"}


def test_pipeline_catches_fabrication(tmp_path):
    rec = {"id": "EXWD", "ticker": "EXWD", "path": str(SAMPLE / "sample_10k.html"), "report_date": "2026-06-30"}
    rows = extract_filing(rec, FabricatingProvider(), [FIELDS_BY_NAME["revenue"]], text_cache=str(tmp_path))
    assert rows[0]["value"] == 999e6
    assert rows[0]["quote_found"] is False


def test_heuristic_end_to_end(tmp_path):
    rec = {"id": "EXWD", "ticker": "EXWD", "path": str(SAMPLE / "sample_10k.html"), "report_date": "2026-06-30"}
    rows = {r["field"]: r for r in extract_filing(rec, HeuristicProvider(), text_cache=str(tmp_path))}
    assert rows["revenue"]["value"] == 12412e6
    assert rows["eps_diluted"]["value"] == 3.21
    assert rows["total_assets"]["quote_found"] and rows["total_assets"]["number_in_quote"]


def test_cache_unicode_roundtrip_and_empty_cache(tmp_path):
    html = tmp_path / "f.htm"
    html.write_text("<html><body><p>☒ Annual report</p></body></html>", encoding="utf-8")
    cache_dir = tmp_path / "text"
    first = load_filing_text(html, cache_dir)
    assert "☒" in first
    assert load_filing_text(html, cache_dir) == first  # served from cache
    (cache_dir / "f.txt").write_text("", encoding="utf-8")  # simulate a truncated cache
    assert load_filing_text(html, cache_dir) == first


def test_split_table_keeps_scale():
    text = "\n".join(["(In millions, except per share amounts)", "Revenue | 1,000 | 900"]
                     + [f"Line item {i} | {i},000 | {i},100" for i in range(60)]
                     + ["Net cash provided by operating activities | 2,903 | 2,500"])
    chunks = chunk_text(text, max_chars=300)
    assert len(chunks) > 2
    last = chunks[-1]
    assert "(In millions" not in last and last.startswith("[amounts in millions]")
    assert detect_scale(last) == "millions"
    assert all(detect_scale(c) == "millions" for c in chunks)


def test_no_scale_tag_without_hint():
    chunks = chunk_text("\n".join(f"Row {i} | {i}" for i in range(100)), max_chars=200)
    assert not any("[amounts in" in c for c in chunks)


def test_demo_all_correct(tmp_path):
    from finextract.cli import run_demo
    run_demo(str(tmp_path))
    rows = list(csv.DictReader(open(tmp_path / "demo" / "reports" / "demo_items.csv", encoding="utf-8")))
    assert rows and all(r["class"] == "correct" for r in rows if r["label"])


class _FakeResp:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code, self._payload, self.text = status, payload, text
        self.headers = headers or {}

    def json(self):
        return self._payload


def _openai_local(monkeypatch, **env):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("FINEXTRACT_CONTEXT_TOKENS", raising=False)
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    monkeypatch.delenv("FINEXTRACT_REASONING_EFFORT", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return OpenAICompatProvider(model="fake-model")


def test_json_mode_falls_back_when_rejected(monkeypatch, caplog):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        if "response_format" in json:
            return _FakeResp(400, text='{"error": "response_format not supported"}')
        content = '{"value": 2148, "scale": "millions", "quote": "Operating income | 2,148"}'
        return _FakeResp(200, {"choices": [{"message": {"content": content}}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    monkeypatch.setattr("finextract.llm.requests.post", fake_post)
    p = _openai_local(monkeypatch)
    f = FIELDS_BY_NAME["operating_income"]
    with caplog.at_level("WARNING", logger="finextract.llm"):
        out = p.extract(f, "X", "2026-06-30", ["Operating income | 2,148"])
    assert out["value"] == 2148 and out["usage"]["input_tokens"] == 10
    assert "response_format" in calls[0] and "response_format" not in calls[1]
    assert calls[0]["reasoning_effort"] == "none" and "reasoning_effort" not in calls[1]
    assert calls[1]["temperature"] == 0
    assert p.json_mode is False and "json_object" in caplog.text
    p.extract(f, "X", "2026-06-30", ["Operating income | 2,148"])
    assert len(calls) == 3 and "response_format" not in calls[2]  # no retry with JSON mode once rejected


def test_context_warning(monkeypatch, caplog):
    p = _openai_local(monkeypatch, OLLAMA_CONTEXT_LENGTH="1000")
    with caplog.at_level("WARNING", logger="finextract.llm"):
        assert p._check_context("x" * 200) < 1000
        assert "exceeds context" not in caplog.text
        p._check_context("x" * 8000)
    assert "exceeds context 1000" in caplog.text


def test_request_timeout_configurable(monkeypatch):
    from finextract.llm import _post_with_retry
    seen = []

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.append(timeout)
        return _FakeResp(200, {"ok": True})

    monkeypatch.setattr("finextract.llm.requests.post", fake_post)
    monkeypatch.delenv("FINEXTRACT_TIMEOUT", raising=False)
    _post_with_retry("http://x", {}, {})
    monkeypatch.setenv("FINEXTRACT_TIMEOUT", "30")
    _post_with_retry("http://x", {}, {})
    assert seen == [600.0, 30.0]


def test_min_interval_and_retry_after(monkeypatch):
    import finextract.llm as llm
    sleeps, clock = [], [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(llm.time, "sleep", lambda s: (sleeps.append(round(s, 1)), clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(llm, "_last_request", [0.0])
    monkeypatch.setenv("FINEXTRACT_MIN_INTERVAL", "25")
    resps = [_FakeResp(429, text="Rate limit reached on tokens per minute (TPM)", headers={"retry-after": "7"}),
             _FakeResp(200, {"ok": 1}), _FakeResp(200, {"ok": 2})]
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: resps.pop(0))
    assert llm._post_with_retry("http://x", {}, {}) == {"ok": 1}
    assert llm._post_with_retry("http://x", {}, {}) == {"ok": 2}
    # first call: no wait; 429 -> Retry-After 7s; retry waits the rest of the 25s gap; next call waits 25s
    assert sleeps == [7, 18, 25]


@pytest.mark.parametrize("text,retry_after", [
    ("Rate limit reached on tokens per day (TPD): Limit 200000", "60"),
    ("Rate limit reached", "3600"),  # longer than FINEXTRACT_MAX_WAIT (600 by default)
])
def test_daily_limit_raises(monkeypatch, text, retry_after):
    import finextract.llm as llm
    monkeypatch.delenv("FINEXTRACT_MIN_INTERVAL", raising=False)
    monkeypatch.delenv("FINEXTRACT_MAX_WAIT", raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: pytest.fail("must not sleep on a daily limit"))
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _FakeResp(429, text=text, headers={"retry-after": retry_after}))
    with pytest.raises(llm.DailyLimitReached):
        llm._post_with_retry("http://x", {}, {})


class QuotaProvider:
    """Answers `budget` fields, then hits the daily limit."""
    name = "quota"

    def __init__(self, budget):
        self.budget, self.calls = budget, []

    def extract(self, field, company, period, chunks):
        from finextract.llm import DailyLimitReached
        if len(self.calls) >= self.budget:
            raise DailyLimitReached("429 tokens per day")
        self.calls.append(field.name)
        return HeuristicProvider().extract(field, company, period, chunks)


def test_daily_limit_stops_and_resume_finishes(tmp_path):
    from finextract.config import FIELDS
    from finextract.evaluate import load_predictions
    rec = {"id": "EXWD", "ticker": "EXWD", "path": str(SAMPLE / "sample_10k.html"), "report_date": "2026-06-30"}
    first = QuotaProvider(budget=4)
    with pytest.raises(SystemExit, match="--resume"):
        run_extraction([rec], first, "r", workers=1, data_dir=str(tmp_path))
    meta, preds = load_predictions(tmp_path / "predictions" / "r.jsonl")
    assert meta["run"] == "r" and len(preds) == 4
    second = QuotaProvider(budget=100)
    run_extraction([rec], second, "r", workers=1, data_dir=str(tmp_path), resume=True)
    assert second.calls == [f.name for f in FIELDS][4:]  # only the remaining fields
    meta, preds = load_predictions(tmp_path / "predictions" / "r.jsonl")
    assert len(preds) == len(FIELDS) and meta["run"] == "r"
