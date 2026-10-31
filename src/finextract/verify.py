"""Stage 2, "snap to source": re-read each answer's number from the real filing line.

Post-processing only, no LLM calls. The model usually finds the right line and then slips
a digit while copying the number (20,935 -> 20,835). So we:
  1. fuzzy-match the model's quote to the closest real line in the filing text
     (difflib ratio >= MIN_RATIO and the same row label), else mark it unverified (value=None);
  2. from that line, take the number in the column closest to the model's value;
  3. apply the scale the model reported for that table.
"""
import difflib
import json
from pathlib import Path

from .config import FIELDS_BY_NAME
from .numbers import apply_scale, normalize_ws, parse_number
from .textproc import load_filing_text

MIN_RATIO = 0.85


def _norm(s):
    return normalize_ws(s).replace("’", "'").replace("‘", "'")


def _label(line):
    return _norm(line.split("|")[0]).rstrip(":").strip()


def _cell_numbers(line):
    """Numbers in the value columns of a ' | '-separated row (the label column is skipped)."""
    out = []
    for cell in line.split("|")[1:]:
        cell = cell.strip()
        if "%" in cell:
            continue
        v = parse_number(cell.replace(" ", ""))
        if v is not None:
            out.append((cell, v))
    return out


def _digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _digit_distance(a, b):
    """Levenshtein distance between two digit strings."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def best_line(quote, lines):
    """Closest real line to `quote` as (line, ratio), or (None, best_ratio) if none qualifies."""
    q = _norm(quote)
    if not q:
        return None, 0.0
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(q)  # SequenceMatcher caches the second sequence
    ncells = q.count("|") + 1
    best, best_r = None, 0.0
    for line in lines:
        # Models often quote only the first column or two, so compare against the line cut to the
        # same number of columns; otherwise a short wrong row can outscore the full right one.
        n = "|".join(_norm(line).split("|")[:ncells]).strip()
        sm.set_seq1(n)
        if sm.real_quick_ratio() <= best_r or sm.quick_ratio() <= best_r:
            continue
        r = sm.ratio()
        if r > best_r:
            best, best_r = line, r
    if best is None or best_r < MIN_RATIO or _label(best) != _label(quote):
        return None, best_r
    return best, best_r


def snap_row(row, lines):
    """Return a copy of a prediction row with its value re-read from the matched filing line."""
    out = dict(row, verified=False, verified_line=None, match_ratio=None, value_changed=False)
    model_raw = parse_number(row.get("value_raw"))
    if model_raw is None:
        return out  # nothing was answered; nothing to verify
    line, ratio = best_line(row.get("quote") or "", lines)
    out["match_ratio"] = round(ratio, 3)
    nums = _cell_numbers(line) if line else []
    if not nums:
        out.update(value=None, value_raw=None, quote_found=False, number_in_quote=False)
        return out
    # A copy slip changes a digit or two, so pick the column whose digits differ least from the
    # model's number (67,189 -> 67,589, not the numerically nearer prior-year 67,060).
    model_digits = _digits(row.get("value_raw"))
    cell, raw = min(nums, key=lambda cv: (_digit_distance(_digits(cv[0]), model_digits), abs(cv[1] - model_raw)))
    unit = FIELDS_BY_NAME[row["field"]].unit if row.get("field") in FIELDS_BY_NAME else "USD"
    value = apply_scale(raw, "units" if unit != "USD" else row.get("scale"))
    # Grounded by construction: the line is from the filing and the number is from that line.
    out.update(value=value, value_raw=cell, quote=line, quote_found=True, number_in_quote=True,
               verified=True, verified_line=line, value_changed=value != row.get("value"))
    return out


def verify_run(run_name, data_dir="data"):
    data = Path(data_dir)
    src = data / "predictions" / f"{run_name}.jsonl"
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines()]
    meta = rows[0]["_meta"] if "_meta" in rows[0] else {}
    rows = [r for r in rows if "_meta" not in r]
    filings = {r["id"]: r for r in map(json.loads, (data / "filings.jsonl").read_text(encoding="utf-8").splitlines())}
    lines_by_filing = {}
    out_rows = []
    for r in rows:
        fid = r["filing_id"]
        if fid not in lines_by_filing:
            text = load_filing_text(filings[fid]["path"], str(data / "text"))
            lines_by_filing[fid] = [l for l in text.splitlines() if l.strip()]
        out_rows.append(snap_row(r, lines_by_filing[fid]))
    dst = data / "predictions" / f"{run_name}_verified.jsonl"
    meta = dict(meta, run=f"{run_name}_verified", verified_from=run_name)
    with dst.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": meta}) + "\n")
        for r in out_rows:
            fh.write(json.dumps(r) + "\n")
    answered = [r for r in out_rows if parse_number(r.get("value_raw")) is not None or r["match_ratio"] is not None]
    print(f"  {sum(r['verified'] for r in out_rows)}/{len(answered)} answers verified, "
          f"{sum(r['value_changed'] for r in out_rows if r['verified'])} values changed, "
          f"{sum(1 for r in answered if not r['verified'])} set to None (no matching line)")
    print(f"  wrote {dst}")
    return out_rows
