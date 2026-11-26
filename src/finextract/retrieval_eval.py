"""Retrieval-only benchmark: does the top-k contain a chunk with the gold value? No LLM.

A chunk is *relevant* to a labeled field if one of its table rows has a value cell that equals the
label exactly, after the same normalisation the verifier uses:
  - cells are parsed with verify._cell_numbers (label column skipped, % cells ignored, "(1,234)" = -1234);
  - USD fields are scaled by the chunk's scale hint (detect_scale; chunk_text carries
    "[amounts in millions]" forward), per-share and other non-USD fields are compared unscaled;
  - equality is numbers_match with rel_tol=1e-9 (float noise only).
Matching is by value, so a chunk that shows the same number in another context also counts.

Recall@k = fields with a relevant chunk in the top k / all labeled fields (unreachable fields, with
no relevant chunk anywhere in the filing, stay in the denominator and are reported separately).
MRR = mean over all labeled fields of 1/rank of the first relevant chunk within the top 10 (else 0).
"""
import csv
import json
import math
from pathlib import Path

from .config import FIELDS, SPLITS
from .labels import load_labels
from .numbers import apply_scale, detect_scale, numbers_match
from .retrieve import make_retriever
from .textproc import chunk_text, load_filing_text
from .verify import _cell_numbers

KS = (3, 6, 10)
MRR_DEPTH = 10


def is_relevant(chunk, label_value, unit="USD"):
    scale = detect_scale(chunk) if unit == "USD" else "units"
    for line in chunk.splitlines():
        if "|" not in line:
            continue
        for _, v in _cell_numbers(line):
            if numbers_match(apply_scale(v, scale), label_value, rel_tol=1e-9):
                return True
    return False


def split_filings(split, data_dir="data"):
    if split not in SPLITS:
        raise SystemExit(f"unknown split {split!r}; expected one of {sorted(SPLITS)}")
    tickers = set(SPLITS[split])
    recs = [json.loads(l) for l in (Path(data_dir) / "filings.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in recs if r["ticker"] in tickers]


def evaluate_retrieval(split, retriever="bm25", data_dir="data", ks=KS, **retriever_kw):
    data = Path(data_dir)
    labels = load_labels(data / "labels.csv")
    items = []
    for rec in split_filings(split, data_dir):
        chunks = chunk_text(load_filing_text(rec["path"], str(data / "text")))
        index = None
        for f in FIELDS:
            lab = labels.get((rec["id"], f.name))
            if lab is None:
                continue
            if index is None:
                kw = dict(retriever_kw)
                if retriever != "bm25":
                    kw.setdefault("cache_key", rec["id"])
                index = make_retriever(retriever, chunks, **kw)
            relevant = {i for i, c in enumerate(chunks) if is_relevant(c, lab["value"], f.unit)}
            top = index.search(f.query, k=max(max(ks), MRR_DEPTH))
            rank = next((r for r, i in enumerate(top, 1) if i in relevant), None)
            items.append({"filing_id": rec["id"], "field": f.name, "label": lab["value"],
                          "relevant_chunks": len(relevant), "first_relevant_rank": rank or "",
                          "top_ids": " ".join(map(str, top))})
    n = len(items)
    hits = {k: sum(1 for it in items if it["first_relevant_rank"] and it["first_relevant_rank"] <= k) for k in ks}
    rr = sum(1.0 / it["first_relevant_rank"] for it in items
             if it["first_relevant_rank"] and it["first_relevant_rank"] <= MRR_DEPTH)
    return {"split": split, "retriever": retriever, "n": n, "hits": hits, "rr_sum": rr,
            "mrr": rr / n if n else 0.0, "unreachable": sum(1 for it in items if not it["relevant_chunks"]),
            "filings": len({it["filing_id"] for it in items}), "items": items}


def floor_to(x, places):
    """Truncate (never round up) so no reported figure is higher than measured."""
    m = 10 ** places
    return math.floor(x * m + 1e-9) / m


def pct(h, n):
    return f"{floor_to(100 * h / n, 1):.1f}% ({h}/{n})" if n else "n/a (0/0)"


def mrr_str(r):
    return f"{floor_to(r['mrr'], 3):.3f}"


def write_items(result, report_dir="reports"):
    rep = Path(report_dir)
    rep.mkdir(parents=True, exist_ok=True)
    path = rep / f"retrieval_{result['retriever']}_{result['split']}_items.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(result["items"][0].keys()))
        w.writeheader()
        w.writerows(result["items"])
    return path


def summary_line(r):
    return (f"{r['split']:>6} {r['retriever']:>6}: " + "  ".join(f"R@{k} {pct(r['hits'][k], r['n'])}" for k in sorted(r["hits"]))
            + f"  MRR@{MRR_DEPTH} {mrr_str(r)}  unreachable {r['unreachable']}/{r['n']}")


DEFINITION = """\
**Relevant chunk:** a chunk with a table row whose value cell equals the label exactly, using the
verifier's normalisation (`verify._cell_numbers`: label column skipped, `%` cells ignored, `(1,234)` =
-1234; USD fields scaled by the chunk's scale hint, per-share fields unscaled; `numbers_match`,
rel_tol=1e-9). Matching is by value, so the same number appearing in another context also counts.

**Recall@k** = labeled fields with a relevant chunk in the top k / all labeled fields. **MRR@10** = mean
of 1/rank of the first relevant chunk within the top 10 (0 if none). *Unreachable* = no relevant chunk
anywhere in the filing; those fields stay in the denominator. Percentages and MRR are truncated, never
rounded up. Queries are each field's `query` from `config.py`; chunks come from `textproc.chunk_text`,
exactly as in extraction."""


def table_rows(results):
    head = ["| Split | Retriever | n | Recall@3 | Recall@6 | Recall@10 | MRR@10 | Unreachable |",
            "|---|---|---|---|---|---|---|---|"]
    for r in results:
        head.append(f"| {r['split']} | {r['retriever']} | {r['n']} | " + " | ".join(pct(r["hits"][k], r["n"]) for k in KS)
                    + f" | {mrr_str(r)} | {r['unreachable']}/{r['n']} |")
    return head


def write_report(results, path, title, notes=""):
    lines = [f"# {title}", "", DEFINITION, ""] + table_rows(results)
    if notes:
        lines += ["", notes]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
