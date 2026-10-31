import json
from pathlib import Path

import pytest

from finextract.config import FIELDS_BY_NAME
from finextract.evaluate import classify
from finextract.extract import extract_filing, grounding
from finextract.labels import label_filing
from finextract.llm import HeuristicProvider, parse_json_response
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
