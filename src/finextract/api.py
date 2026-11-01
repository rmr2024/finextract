"""HTTP service over the SQLite store, plus a one-page dashboard at "/".

Install with `pip install -e ".[api]"`; run with `finextract serve` (binds 127.0.0.1 by default).
POST /extract only re-runs filings that are already downloaded (data/filings.jsonl); the service
never contacts SEC, and uses an LLM provider only if its environment variables are already set.
"""
import json
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .store import Store, valid_run_name

STATIC = Path(__file__).parent / "static"
PROVIDERS = ("heuristic", "anthropic", "openai")


class ExtractRequest(BaseModel):
    ticker: str
    run: str
    provider: str = "heuristic"
    model: str = None
    k: int = 4


def _provider_ready(name, model=None):
    """Refuse an LLM provider unless its settings are already in the environment."""
    if name == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY is not set"
    if name == "openai":
        base = os.environ.get("OPENAI_BASE_URL", "")
        if not (os.environ.get("OPENAI_API_KEY") or "localhost" in base or "127.0.0.1" in base):
            return False, "OPENAI_API_KEY (or a local OPENAI_BASE_URL) is not set"
        if not (model or os.environ.get("FINEXTRACT_MODEL")):
            return False, "pass \"model\" or set FINEXTRACT_MODEL"
    return True, ""


def create_app(data_dir="data", db_path=None):
    data = Path(data_dir)
    store = Store(db_path or data / "finextract.db")
    app = FastAPI(title="finextract", description="10-K figure extraction results and jobs")
    app.state.store = store

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/runs")
    def runs():
        return store.runs()

    @app.get("/runs/{run}/summary")
    def summary(run: str):
        s = store.summary(run)
        if s is None:
            raise HTTPException(404, f"run {run!r} not imported; try `finextract import --run {run}`")
        return s

    @app.get("/runs/{run}/filings")
    def filings(run: str):
        if store.summary(run) is None:
            raise HTTPException(404, f"run {run!r} not imported")
        return store.filings(run)

    @app.get("/runs/{run}/filings/{filing_id}")
    def filing(run: str, filing_id: str):
        rows = store.filing(run, filing_id)
        if not rows:
            raise HTTPException(404, f"no fields for {filing_id!r} in run {run!r}")
        return {"run": run, "filing_id": filing_id, "fields": rows}

    @app.post("/extract", status_code=202)
    def extract(req: ExtractRequest, background: BackgroundTasks):
        if not valid_run_name(req.run):
            raise HTTPException(400, "run must be 1-100 chars of letters, digits, _ . - (no leading . or -)")
        if req.provider not in PROVIDERS:
            raise HTTPException(400, f"provider must be one of {PROVIDERS}")
        ok, why = _provider_ready(req.provider, req.model)
        if not ok:
            raise HTTPException(400, f"provider {req.provider!r} not configured: {why}")
        rec = _find_filing(data, req.ticker)
        if rec is None:
            raise HTTPException(404, f"{req.ticker.upper()} is not downloaded; run `finextract download` first")
        job_id = store.create_job(req.run, rec["ticker"], req.provider)
        background.add_task(_run_job, store, job_id, rec, req, str(data))
        return {"job_id": job_id, "status": "queued"}

    @app.get("/jobs/{job_id}")
    def job(job_id: str):
        j = store.job(job_id)
        if j is None:
            raise HTTPException(404, "unknown job")
        return j

    return app


def _find_filing(data, ticker):
    path = data / "filings.jsonl"
    if not path.exists():
        return None
    recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return next((r for r in recs if r["ticker"].upper() == ticker.upper()), None)


def _run_job(store, job_id, rec, req, data_dir):
    from .extract import run_extraction
    from .llm import get_provider
    store.update_job(job_id, "running")
    try:
        provider = get_provider(req.provider, req.model)
        # resume=True appends to an existing run instead of overwriting its other filings
        run_extraction([rec], provider, req.run, k=req.k, workers=1, data_dir=data_dir, resume=True)
        n = store.import_run(req.run, data_dir)
        store.update_job(job_id, "done", f"{rec['id']}: extracted; run {req.run} now has {n} fields")
    except BaseException as e:  # SystemExit from providers / resume checks included
        store.update_job(job_id, "failed", str(e)[:500] or type(e).__name__)
