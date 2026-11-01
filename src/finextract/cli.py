"""Command line: finextract {download,label,extract,evaluate,verify,import,serve,demo}"""
import argparse
import json
import shutil
from pathlib import Path

from .config import DEFAULT_TICKERS, FIELDS, FIELDS_BY_NAME


def _load_filings(data_dir, limit=None, only=None):
    path = Path(data_dir) / "filings.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} not found — run `finextract download` first.")
    recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    if only:
        recs = [r for r in recs if r["ticker"] in {t.upper() for t in only}]
    return recs[:limit] if limit else recs


def main(argv=None):
    p = argparse.ArgumentParser(prog="finextract", description="10-K extraction benchmark")
    p.add_argument("--data-dir", default="data")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="download 10-Ks and XBRL facts from SEC EDGAR")
    d.add_argument("--tickers", nargs="*", default=None)
    d.add_argument("--per-company", type=int, default=1, help="how many recent 10-Ks per company")

    sub.add_parser("label", help="build data/labels.csv from XBRL facts")

    e = sub.add_parser("extract", help="run the extraction pipeline")
    e.add_argument("--provider", default="heuristic", choices=["heuristic", "anthropic", "openai"])
    e.add_argument("--model", default=None)
    e.add_argument("--run", required=True, help="name for this run, e.g. baseline_haiku")
    e.add_argument("--limit", type=int, default=None, help="only the first N filings (cheap test)")
    e.add_argument("--tickers", nargs="*", default=None)
    e.add_argument("--fields", nargs="*", default=None, choices=list(FIELDS_BY_NAME))
    e.add_argument("--k", type=int, default=6, help="chunks retrieved per field")
    e.add_argument("--workers", type=int, default=4)
    e.add_argument("--resume", action="store_true", help="skip fields already done in this run; retry failed ones")

    v = sub.add_parser("evaluate", help="score a run")
    v.add_argument("--run", required=True)

    vf = sub.add_parser("verify", help="snap each answer to its real filing line (offline, no LLM)")
    vf.add_argument("--run", required=True)

    im = sub.add_parser("import", help="load a predictions run + labels into the SQLite store")
    im.add_argument("--run", required=True)
    im.add_argument("--db", default=None, help="default: <data-dir>/finextract.db")

    sv = sub.add_parser("serve", help="start the API + dashboard (needs the [api] extra)")
    sv.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1 (this machine only)")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--db", default=None)

    sub.add_parser("demo", help="run the whole pipeline offline on a bundled sample filing")

    a = p.parse_args(argv)

    if a.cmd == "download":
        from .edgar import download_filings
        tickers = a.tickers or DEFAULT_TICKERS
        print(f"Downloading {len(tickers)} companies x {a.per_company} 10-K(s)...")
        download_filings(tickers, a.data_dir, a.per_company)

    elif a.cmd == "label":
        from .labels import build_labels
        build_labels(a.data_dir)

    elif a.cmd == "extract":
        from .extract import run_extraction
        from .llm import get_provider
        provider = get_provider(a.provider, a.model)
        fields = [FIELDS_BY_NAME[f] for f in a.fields] if a.fields else FIELDS
        filings = _load_filings(a.data_dir, a.limit, a.tickers)
        print(f"Extracting {len(fields)} fields from {len(filings)} filings with {provider.name}...")
        run_extraction(filings, provider, a.run, fields, a.k, a.workers, a.data_dir, resume=a.resume)

    elif a.cmd == "evaluate":
        from .evaluate import evaluate
        evaluate(a.run, a.data_dir)

    elif a.cmd == "verify":
        from .verify import verify_run
        verify_run(a.run, a.data_dir)

    elif a.cmd == "import":
        from .store import Store
        db = a.db or str(Path(a.data_dir) / "finextract.db")
        n = Store(db).import_run(a.run, a.data_dir)
        print(f"  imported {n} fields from run {a.run} into {db}")

    elif a.cmd == "serve":
        try:
            import uvicorn
            from .api import create_app
        except ImportError:
            raise SystemExit('The service needs the api extra: pip install -e ".[api]"')
        if a.host not in ("127.0.0.1", "localhost", "::1"):
            print(f"  warning: binding {a.host} exposes the API beyond this machine; there is no auth")
        print(f"  dashboard: http://{a.host}:{a.port}/")
        uvicorn.run(create_app(a.data_dir, a.db), host=a.host, port=a.port)

    elif a.cmd == "demo":
        run_demo(a.data_dir)


def run_demo(data_dir):
    """Offline smoke test: bundled synthetic filing -> labels -> heuristic extraction -> report."""
    from .evaluate import evaluate
    from .extract import run_extraction
    from .labels import build_labels
    from .llm import HeuristicProvider

    sample = Path(__file__).parent / "sample"
    data = Path(data_dir) / "demo"
    (data / "raw").mkdir(parents=True, exist_ok=True)
    (data / "cache").mkdir(parents=True, exist_ok=True)
    shutil.copy(sample / "sample_10k.html", data / "raw" / "EXWD_0000000001-26-000001.html")
    shutil.copy(sample / "sample_companyfacts.json", data / "cache" / "facts_1.json")
    rec = {"id": "EXWD_0000000001-26-000001", "ticker": "EXWD", "cik": 1,
           "company": "Example Widgets Corp (synthetic)", "accession": "0000000001-26-000001",
           "report_date": "2026-06-30", "path": str(data / "raw" / "EXWD_0000000001-26-000001.html")}
    (data / "filings.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    print("1/3 labels")
    build_labels(str(data))
    print("2/3 extraction (heuristic, no API key needed)")
    run_extraction([rec], HeuristicProvider(), "demo", data_dir=str(data))
    print("3/3 evaluation")
    evaluate("demo", str(data), report_dir=str(data / "reports"))


if __name__ == "__main__":
    main()
