"""Ground-truth labels from the company's own XBRL tags.

Each 10-K tags its financial statement numbers in XBRL. The SEC "companyfacts"
API returns every tagged value with the accession number of the filing that
reported it, so we can look up exactly what *this* filing said.

Caveat: XBRL is the filer's tagging, not an
independent audit. Companies pick different tags for "revenue", and some
values are restated later. That's why labels.csv has a `verified` column:
spot-check a sample by hand against the filing and record what you find.
"""
import csv
import json
from datetime import date
from pathlib import Path

from .config import FIELDS


def _days(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _candidates(facts, tag, unit, accession, period):
    entries = facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit, [])
    out = []
    for e in entries:
        if e.get("accn") != accession or not e.get("form", "").startswith("10-K"):
            continue
        if period == "duration":
            if "start" not in e or not (330 <= _days(e["start"], e["end"]) <= 400):
                continue
        elif "start" in e:
            continue
        out.append(e)
    return out


def label_filing(facts, accession, fields=FIELDS):
    """Return {field: {value, prior_value, period_end, tag}} for one filing (None if untagged)."""
    labels = {}
    for f in fields:
        result = None
        for tag in f.xbrl_tags:
            cands = _candidates(facts, tag, f.unit, accession, f.period)
            if not cands:
                continue
            ends = sorted({c["end"] for c in cands}, reverse=True)
            current = next(c for c in cands if c["end"] == ends[0])
            prior = next((c for c in cands if len(ends) > 1 and c["end"] == ends[1]), None)
            result = {"value": current["val"], "prior_value": prior["val"] if prior else None,
                      "period_end": current["end"], "tag": tag}
            break
        labels[f.name] = result
    return labels


def build_labels(data_dir="data"):
    data = Path(data_dir)
    filings = [json.loads(l) for l in (data / "filings.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = []
    for rec in filings:
        facts_path = data / "cache" / f"facts_{rec['cik']}.json"
        if not facts_path.exists():
            print(f"  skip {rec['id']}: no company facts cached (run download first)")
            continue
        labels = label_filing(json.loads(facts_path.read_text(encoding="utf-8")), rec["accession"])
        for fname, lab in labels.items():
            rows.append({
                "filing_id": rec["id"], "field": fname,
                "value": "" if lab is None else lab["value"],
                "prior_value": "" if lab is None or lab["prior_value"] is None else lab["prior_value"],
                "period_end": "" if lab is None else lab["period_end"],
                "xbrl_tag": "" if lab is None else lab["tag"],
                "verified": "", "notes": "",
            })
    out = data / "labels.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["filing_id"])
        w.writeheader()
        w.writerows(rows)
    have = sum(1 for r in rows if r["value"] != "")
    print(f"  wrote {out}: {have}/{len(rows)} field-labels found")
    return rows


def load_labels(path):
    labels = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["value"] == "":
                continue
            # A human correction (verified=fixed:<number>) overrides the XBRL value.
            v = r.get("verified", "")
            value = float(v.split(":", 1)[1]) if v.startswith("fixed:") else float(r["value"])
            labels[(r["filing_id"], r["field"])] = {
                "value": value,
                "prior_value": float(r["prior_value"]) if r["prior_value"] else None,
                "period_end": r["period_end"],
            }
    return labels
