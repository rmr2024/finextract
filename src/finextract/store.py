"""SQLite store for runs, per-field results and background jobs.

One file (data/finextract.db by default), stdlib only. Each call opens its own connection, so the
store is safe to use from the API's worker threads.
"""
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .evaluate import classify, load_predictions, summarize
from .labels import load_labels

RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run TEXT PRIMARY KEY, provider TEXT, model TEXT, k INTEGER,
    prompt_version TEXT, prompt_hash TEXT, verified_from TEXT, imported_at TEXT, meta_json TEXT
);
CREATE TABLE IF NOT EXISTS items (
    run TEXT, filing_id TEXT, field TEXT,
    value REAL, value_raw TEXT, scale TEXT, quote TEXT, quote_found INTEGER, number_in_quote INTEGER,
    verified INTEGER, verified_line TEXT, match_ratio REAL, value_changed INTEGER,
    label REAL, prior_label REAL, class TEXT, answered INTEGER, grounded INTEGER,
    latency_s REAL, error TEXT,
    PRIMARY KEY (run, filing_id, field)
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, run TEXT, ticker TEXT, provider TEXT, status TEXT,
    created_at TEXT, finished_at TEXT, message TEXT
);
"""


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def valid_run_name(name):
    """Run names become file names, so only allow a safe character set."""
    return bool(RUN_NAME.match(name or ""))


class Store:
    def __init__(self, path="data/finextract.db"):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(SCHEMA)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    # --- runs ---------------------------------------------------------------
    def import_run(self, run, data_dir="data"):
        """Load data/predictions/<run>.jsonl joined with labels.csv. Replaces any earlier import."""
        if not valid_run_name(run):
            raise ValueError(f"invalid run name: {run!r}")
        data = Path(data_dir)
        path = data / "predictions" / f"{run}.jsonl"
        if not path.exists():
            raise FileNotFoundError(path)
        meta, preds = load_predictions(path)
        labels = load_labels(data / "labels.csv") if (data / "labels.csv").exists() else {}
        rows = []
        for key, p in preds.items():
            lab = labels.get(key)
            answered = p.get("value") is not None
            cls = classify(p.get("value"), lab) if lab else "unlabeled"
            grounded = bool(p.get("quote_found") and p.get("number_in_quote")) if answered else None
            rows.append((run, key[0], key[1], p.get("value"), _s(p.get("value_raw")), p.get("scale"),
                         p.get("quote") or "", _b(p.get("quote_found")), _b(p.get("number_in_quote")),
                         _b(p.get("verified")), p.get("verified_line"), p.get("match_ratio"),
                         _b(p.get("value_changed")), lab["value"] if lab else None,
                         lab["prior_value"] if lab else None, cls, int(answered), _b(grounded),
                         p.get("latency_s"), p.get("error")))
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM items WHERE run = ?", (run,))
            db.executemany(f"INSERT INTO items VALUES ({','.join('?' * 20)})", rows)
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                       (run, meta.get("provider"), meta.get("model"), meta.get("k"),
                        meta.get("prompt_version"), meta.get("prompt_hash"), meta.get("verified_from"),
                        _now(), json.dumps(meta)))
        return len(rows)

    def runs(self):
        with closing(self._connect()) as db:
            out = [dict(r) for r in db.execute(
                "SELECT run, provider, model, k, prompt_version, prompt_hash, verified_from, imported_at "
                "FROM runs ORDER BY run")]
            for r in out:
                r["filings"] = db.execute("SELECT COUNT(DISTINCT filing_id) FROM items WHERE run = ?",
                                          (r["run"],)).fetchone()[0]
        return out

    def summary(self, run):
        """Same metrics as `finextract evaluate`, over the labeled fields of the run."""
        with closing(self._connect()) as db:
            if not db.execute("SELECT 1 FROM runs WHERE run = ?", (run,)).fetchone():
                return None
            rows = [dict(r) for r in db.execute(
                "SELECT class, answered, grounded FROM items WHERE run = ? AND class != 'unlabeled'", (run,))]
            total = db.execute("SELECT COUNT(*) FROM items WHERE run = ?", (run,)).fetchone()[0]
        if not rows:
            return {"run": run, "n": 0, "fields_total": total}
        s = summarize([{"class": r["class"], "answered": bool(r["answered"]), "grounded": bool(r["grounded"])}
                       for r in rows])
        s["classes"] = dict(s["classes"])
        return dict(s, run=run, fields_total=total)

    def filings(self, run):
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                "SELECT filing_id, COUNT(*) AS fields, SUM(class = 'correct') AS correct, "
                "SUM(class NOT IN ('correct', 'unlabeled')) AS wrong FROM items WHERE run = ? "
                "GROUP BY filing_id ORDER BY filing_id", (run,))]

    def filing(self, run, filing_id):
        with closing(self._connect()) as db:
            rows = [dict(r) for r in db.execute(
                "SELECT field, value, value_raw, scale, label, prior_label, class, answered, grounded, "
                "quote, quote_found, verified, verified_line, match_ratio, value_changed, error "
                "FROM items WHERE run = ? AND filing_id = ? ORDER BY rowid", (run, filing_id))]
        for r in rows:
            r["source_line"] = r["verified_line"] or (r["quote"] if r["quote_found"] else None)
        return rows

    # --- jobs ---------------------------------------------------------------
    def create_job(self, run, ticker, provider):
        job_id = uuid.uuid4().hex[:12]
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                       (job_id, run, ticker, provider, "queued", _now(), None, None))
        return job_id

    def update_job(self, job_id, status, message=None):
        done = status in ("done", "failed")
        with closing(self._connect()) as db, db:
            db.execute("UPDATE jobs SET status = ?, message = ?, finished_at = ? WHERE id = ?",
                       (status, message, _now() if done else None, job_id))

    def job(self, job_id):
        with closing(self._connect()) as db:
            r = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(r) if r else None


def _b(v):
    return None if v is None else int(bool(v))


def _s(v):
    return None if v is None else str(v)
