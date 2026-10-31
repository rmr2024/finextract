"""Baseline pipeline: retrieve -> extract -> record grounding evidence.

No verification or retries on purpose: this is the baseline you measure first.
Stage 2 adds the fix and compares against these numbers.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import FIELDS
from .numbers import apply_scale, find_numbers, normalize_ws, numbers_match, parse_number
from .retrieve import BM25
from .textproc import chunk_text, load_filing_text


def grounding(value_raw, quote, full_text_norm):
    """Is the quote really in the filing, and does it contain the number given?"""
    quote_found = bool(quote) and normalize_ws(quote) in full_text_norm
    raw = parse_number(value_raw)
    number_in_quote = raw is not None and any(
        numbers_match(abs(parse_number(n) or 0), abs(raw), rel_tol=1e-9) for n in find_numbers(quote or ""))
    return quote_found, number_in_quote


def extract_filing(rec, provider, fields=FIELDS, k=6, text_cache="data/text"):
    text = load_filing_text(rec["path"], text_cache)
    text_norm = normalize_ws(text)
    chunks = chunk_text(text)
    index = BM25(chunks)
    results = []
    for f in fields:
        ids = index.search(f.query, k=k)
        ctx = [chunks[i] for i in ids]
        t0 = time.monotonic()
        try:
            out = provider.extract(f, rec.get("company", rec["ticker"]), rec.get("report_date", ""), ctx)
            err = None
        except Exception as e:
            out, err = {"value": None, "scale": "units", "quote": ""}, str(e)[:300]
        raw = parse_number(out.get("value"))
        scale = "units" if f.unit != "USD" else out.get("scale")
        qf, niq = grounding(out.get("value"), out.get("quote", ""), text_norm)
        results.append({
            "filing_id": rec["id"], "field": f.name,
            "value": apply_scale(raw, scale), "value_raw": out.get("value"), "scale": scale,
            "quote": out.get("quote", ""), "quote_found": qf, "number_in_quote": niq,
            "chunk_ids": ids, "latency_s": round(time.monotonic() - t0, 3),
            "usage": out.get("usage", {}), "parse_error": out.get("parse_error", False), "error": err,
        })
    return results


def run_extraction(filings, provider, run_name, fields=FIELDS, k=6, workers=4, data_dir="data"):
    out_path = Path(data_dir) / "predictions" / f"{run_name}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text_cache = str(Path(data_dir) / "text")
    all_rows = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(extract_filing, r, provider, fields, k, text_cache) for r in filings]
        for rec, fut in zip(filings, futures):
            rows = fut.result()
            all_rows.extend(rows)
            got = sum(1 for r in rows if r["value"] is not None)
            print(f"  {rec['id']}: {got}/{len(rows)} fields extracted")
    meta = {"run": run_name, "provider": provider.name, "model": getattr(provider, "model", None), "k": k}
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": meta}) + "\n")
        for r in all_rows:
            fh.write(json.dumps(r) + "\n")
    print(f"  wrote {out_path}")
    return all_rows
