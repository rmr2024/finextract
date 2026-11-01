"""Extraction pipeline: retrieve -> extract -> record grounding evidence.

Deliberately no verification here, so raw extractor behaviour can be measured.
Verification is a separate offline step (verify.py) applied to a finished run.
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .config import FIELDS, LEGACY_V1_CUTOFF
from .llm import DailyLimitReached, prompt_fingerprint
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


def extract_filing(rec, provider, fields=FIELDS, k=6, text_cache="data/text", on_row=None, stop=None):
    """Extract each field; `on_row` sees every row as it is made, `stop` (an Event) ends early."""
    if not fields:
        return []
    text = load_filing_text(rec["path"], text_cache)
    text_norm = normalize_ws(text)
    chunks = chunk_text(text)
    index = BM25(chunks)
    results = []
    for f in fields:
        if stop is not None and stop.is_set():
            break
        ids = index.search(f.query, k=k)
        ctx = [chunks[i] for i in ids]
        t0 = time.monotonic()
        try:
            out = provider.extract(f, rec.get("company", rec["ticker"]), rec.get("report_date", ""), ctx)
            err = None
        except DailyLimitReached:
            raise
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
        if on_row:
            on_row(results[-1])
    return results


def _done_keys(path):
    """(filing_id, field) pairs already extracted without an error in an earlier run."""
    done = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if "_meta" not in r:
            done[(r["filing_id"], r["field"])] = r["error"] is None
    return {k for k, ok in done.items() if ok}


def _file_started_at(path):
    """Creation time of a predictions file (Windows birth time); the start of a run made before
    runs recorded started_at. Unreliable for files git has rewritten."""
    st = os.stat(path)
    return datetime.fromtimestamp(getattr(st, "st_birthtime", None) or st.st_ctime).astimezone()


def _check_prompt(path, version, phash):
    """Refuse to resume a run whose rows were made with a different prompt."""
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    meta = next((r["_meta"] for r in rows if "_meta" in r), {})
    seen = {(r.get("prompt_version"), r["prompt_hash"]) for r in rows if r.get("prompt_hash")}
    if meta.get("prompt_hash"):
        seen.add((meta.get("prompt_version"), meta["prompt_hash"]))
    if not seen:  # legacy run, written before prompt hashes existed
        started = datetime.fromisoformat(meta["started_at"]) if meta.get("started_at") else _file_started_at(path)
        if started >= datetime.fromisoformat(LEGACY_V1_CUTOFF):
            raise SystemExit(f"Can't resume {path.name}: it has no prompt hash and started at "
                             f"{started.isoformat(timespec='seconds')}, after the v2 wording existed, so its "
                             f"prompt is unknown. Start a new --run name.")
        seen = {("v1", prompt_fingerprint("v1")[1])}
    if seen != {(version, phash)}:
        made = ", ".join(f"{v} ({h})" for v, h in sorted(seen, key=str))
        raise SystemExit(f"Can't resume {path.name}: it was made with prompt {made}, but the current prompt is "
                         f"{version} ({phash}). Set FINEXTRACT_PROMPT_VERSION to match, or start a new --run name.")


def run_extraction(filings, provider, run_name, fields=FIELDS, k=6, workers=4, data_dir="data", resume=False):
    """Rows are appended as they finish, so an interrupted run keeps its work.

    With resume=True, fields that already have an error-free row are skipped; failed ones are
    retried and the newer row wins (evaluate keeps the last row per key).
    """
    out_path = Path(data_dir) / "predictions" / f"{run_name}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text_cache = str(Path(data_dir) / "text")
    version, phash = prompt_fingerprint()
    if resume and out_path.exists():
        _check_prompt(out_path, version, phash)
    done = _done_keys(out_path) if resume and out_path.exists() else set()
    if not (resume and out_path.exists()):
        meta = {"run": run_name, "provider": provider.name, "model": getattr(provider, "model", None), "k": k,
                "prompt_version": version, "prompt_hash": phash,
                "started_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        out_path.write_text(json.dumps({"_meta": meta}) + "\n", encoding="utf-8")
    if done:
        print(f"  resuming: {len(done)} fields already done")
    lock, stop, all_rows = threading.Lock(), threading.Event(), []

    def write(row):
        row.update(prompt_version=version, prompt_hash=phash)
        with lock, out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    todo = [(r, [f for f in fields if (r["id"], f.name) not in done]) for r in filings]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(extract_filing, r, provider, fs, k, text_cache, write, stop) for r, fs in todo]
        for (rec, fs), fut in zip(todo, futures):
            try:
                rows = fut.result()
            except DailyLimitReached as e:
                stop.set()
                for f in futures:
                    f.cancel()
                print(f"  stopped: {e}")
                raise SystemExit(f"Daily limit reached. Rows so far are in {out_path}; "
                                 f"re-run the same command with --resume to continue.")
            all_rows.extend(rows)
            got = sum(1 for r in rows if r["value"] is not None)
            print(f"  {rec['id']}: {got}/{len(rows)} fields extracted" + (" (rest done earlier)" if len(fs) < len(fields) else ""))
    print(f"  wrote {out_path}")
    return all_rows
