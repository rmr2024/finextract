"""Minimal SEC EDGAR client.

SEC rules: identify yourself with a User-Agent ("Name email") and stay under
10 requests/second. Set SEC_USER_AGENT in your environment.
"""
import json
import os
import time
from pathlib import Path

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/{doc}"


class EdgarClient:
    def __init__(self, user_agent=None, min_interval=0.15, cache_dir="data/cache"):
        ua = user_agent or os.environ.get("SEC_USER_AGENT")
        if not ua:
            raise SystemExit(
                'Set SEC_USER_AGENT first, e.g.  export SEC_USER_AGENT="Your Name you@example.com"\n'
                "(SEC blocks requests without a real contact.)"
            )
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self.min_interval = min_interval
        self._last = 0.0
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, url, retries=4):
        for attempt in range(retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self.session.get(url, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
        r.raise_for_status()

    def _get_json_cached(self, url, name):
        path = self.cache_dir / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        data = self._get(url).json()
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def ticker_to_cik(self, ticker):
        data = self._get_json_cached(TICKERS_URL, "company_tickers.json")
        t = ticker.upper()
        for row in data.values():
            if row["ticker"].upper() == t:
                return int(row["cik_str"])
        raise KeyError(f"Ticker not found in SEC list: {ticker}")

    def submissions(self, cik):
        return self._get_json_cached(SUBMISSIONS_URL.format(cik=cik), f"submissions_{cik}.json")

    def company_facts(self, cik):
        return self._get_json_cached(FACTS_URL.format(cik=cik), f"facts_{cik}.json")

    def download_document(self, cik, accession, doc):
        url = DOC_URL.format(cik=cik, accn_nodash=accession.replace("-", ""), doc=doc)
        return self._get(url).content


def list_10k_filings(submissions, limit=1):
    """Return the most recent original 10-K filings (no amendments) from a submissions JSON."""
    recent = submissions["filings"]["recent"]
    out = []
    for i, form in enumerate(recent["form"]):
        if form != "10-K":
            continue
        out.append({
            "accession": recent["accessionNumber"][i],
            "primary_doc": recent["primaryDocument"][i],
            "filing_date": recent["filingDate"][i],
            "report_date": recent["reportDate"][i],
        })
        if len(out) >= limit:
            break
    return out


def download_filings(tickers, data_dir="data", per_company=1, client=None):
    """Download 10-K primary documents + XBRL company facts. Writes data/filings.jsonl."""
    client = client or EdgarClient(cache_dir=f"{data_dir}/cache")
    raw_dir = Path(data_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(data_dir) / "filings.jsonl"
    existing = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            existing[rec["id"]] = rec

    for ticker in tickers:
        try:
            cik = client.ticker_to_cik(ticker)
            subs = client.submissions(cik)
            client.company_facts(cik)  # cached for the labeler
            for f in list_10k_filings(subs, per_company):
                fid = f"{ticker.upper()}_{f['accession']}"
                path = raw_dir / f"{fid}.html"
                if not path.exists():
                    path.write_bytes(client.download_document(cik, f["accession"], f["primary_doc"]))
                existing[fid] = {"id": fid, "ticker": ticker.upper(), "cik": cik,
                                 "company": subs.get("name", ""), "path": str(path), **f}
                print(f"  ok  {fid}  (period {f['report_date']})")
        except Exception as e:  # keep going; one bad ticker shouldn't stop the batch
            print(f"  FAIL {ticker}: {e}")

    manifest_path.write_text("".join(json.dumps(r) + "\n" for r in existing.values()), encoding="utf-8")
    return list(existing.values())
