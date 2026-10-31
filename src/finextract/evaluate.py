"""Score a prediction run against labels and classify every error.

Headline metrics:
  accuracy        exact matches (after scale) / labeled fields
  accuracy_tolerant  within 0.5% / labeled fields (the old headline; hides one-digit slips)
  coverage        answered / labeled fields
  ungrounded rate answered values whose quote isn't in the filing or doesn't contain the number
                  (the measurable form of "the model invented it")
  confident-wrong answered but not an exact match — worse than saying "not found"
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .labels import load_labels
from .numbers import numbers_match

CLASSES = ["correct", "near_miss", "missing", "scale_error", "sign_error", "wrong_period", "wrong_other"]


def classify(pred, label):
    v, truth = pred, label["value"]
    if v is None:
        return "missing"
    if numbers_match(v, truth, rel_tol=1e-9):  # exact, allowing only float noise from scaling
        return "correct"
    if numbers_match(v, truth):
        return "near_miss"  # within 0.5%: usually a one-digit slip or a near-identical line item
    if truth and v:
        ratio = abs(v / truth)
        if any(abs(ratio - s) / s < 0.01 for s in (1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9)):
            return "scale_error"
    if numbers_match(-v, truth):
        return "sign_error"
    if label.get("prior_value") is not None and numbers_match(v, label["prior_value"]):
        return "wrong_period"
    return "wrong_other"


def load_predictions(path):
    meta, preds = {}, {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if "_meta" in r:
            meta = r["_meta"]
            continue
        preds[(r["filing_id"], r["field"])] = r
    return meta, preds


def evaluate(run_name, data_dir="data", report_dir="reports"):
    data = Path(data_dir)
    meta, preds = load_predictions(data / "predictions" / f"{run_name}.jsonl")
    labels = load_labels(data / "labels.csv")

    items = []
    for key, lab in labels.items():
        if key not in preds:
            continue
        p = preds[key]
        cls = classify(p["value"], lab)
        answered = p["value"] is not None
        grounded = p["quote_found"] and p["number_in_quote"]
        items.append({"filing_id": key[0], "field": key[1], "label": lab["value"], "pred": p["value"],
                      "class": cls, "answered": answered, "grounded": grounded if answered else "",
                      "quote": p.get("quote", "")})

    if not items:
        raise SystemExit("No overlap between predictions and labels — check filing ids / run name.")

    def summarize(rows):
        n = len(rows)
        ans = [r for r in rows if r["answered"]]
        c = Counter(r["class"] for r in rows)
        return {"n": n, "accuracy": c["correct"] / n, "accuracy_tolerant": (c["correct"] + c["near_miss"]) / n,
                "coverage": len(ans) / n,
                "ungrounded": (sum(1 for r in ans if not r["grounded"]) / len(ans)) if ans else 0.0,
                "confident_wrong": (sum(1 for r in ans if r["class"] != "correct") / len(ans)) if ans else 0.0,
                "classes": c}

    overall = summarize(items)
    by_field = defaultdict(list)
    for r in items:
        by_field[r["field"]].append(r)

    tokens_in = sum((p.get("usage") or {}).get("input_tokens") or 0 for p in preds.values())
    tokens_out = sum((p.get("usage") or {}).get("output_tokens") or 0 for p in preds.values())
    latency = [p.get("latency_s", 0) for p in preds.values()]

    rep = Path(report_dir)
    rep.mkdir(parents=True, exist_ok=True)
    pct = lambda x: f"{100 * x:.1f}%"
    lines = [f"# Run `{run_name}`", "",
             f"Provider: `{meta.get('provider')}`  Model: `{meta.get('model')}`  Retrieved chunks (k): {meta.get('k')}", "",
             "| Metric | Value |", "|---|---|",
             f"| Labeled fields | {overall['n']} |",
             f"| Accuracy (exact) | {pct(overall['accuracy'])} |",
             f"| Accuracy (within 0.5%) | {pct(overall['accuracy_tolerant'])} |",
             f"| Coverage (answered) | {pct(overall['coverage'])} |",
             f"| Ungrounded answers | {pct(overall['ungrounded'])} |",
             f"| Confident-wrong answers | {pct(overall['confident_wrong'])} |",
             f"| Tokens in / out | {tokens_in:,} / {tokens_out:,} |",
             f"| Mean latency per field | {sum(latency) / max(1, len(latency)):.2f}s |", "",
             "## Error breakdown", "", "| Class | Count |", "|---|---|"]
    lines += [f"| {c} | {overall['classes'].get(c, 0)} |" for c in CLASSES]
    lines += ["", "## By field", "", "| Field | n | Accuracy | Coverage | Ungrounded |", "|---|---|---|---|---|"]
    for fname, rows in sorted(by_field.items()):
        s = summarize(rows)
        lines.append(f"| {fname} | {s['n']} | {pct(s['accuracy'])} | {pct(s['coverage'])} | {pct(s['ungrounded'])} |")
    md = rep / f"{run_name}.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (rep / f"{run_name}_items.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(items[0].keys()))
        w.writeheader()
        w.writerows(items)

    print("\n".join(lines[:14]))
    print(f"\n  full report: {md}\n  per-item:    {rep / (run_name + '_items.csv')}")
    return overall
