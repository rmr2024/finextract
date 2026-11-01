"""API tests on the bundled sample filing. No network, no LLM."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from finextract.api import create_app  # noqa: E402
from finextract.cli import run_demo  # noqa: E402
from finextract.store import Store, valid_run_name  # noqa: E402


@pytest.fixture()
def demo(tmp_path):
    run_demo(str(tmp_path))  # builds tmp/demo: filings.jsonl, labels.csv, predictions/demo.jsonl
    data = tmp_path / "demo"
    Store(data / "finextract.db").import_run("demo", str(data))
    return data


@pytest.fixture()
def client(demo):
    return TestClient(create_app(str(demo)))


def test_runs_summary_and_filing(client):
    runs = client.get("/runs").json()
    assert [r["run"] for r in runs] == ["demo"] and runs[0]["filings"] == 1
    s = client.get("/runs/demo/summary").json()
    assert s["n"] > 0 and s["accuracy"] == 1.0 and s["ungrounded"] == 0.0 and s["classes"]["correct"] == s["n"]
    filings = client.get("/runs/demo/filings").json()
    assert len(filings) == 1
    fid = filings[0]["filing_id"]
    d = client.get(f"/runs/demo/filings/{fid}").json()
    by_field = {f["field"]: f for f in d["fields"]}
    rev = by_field["revenue"]
    assert rev["value"] == 12412e6 and rev["label"] == 12412e6 and rev["class"] == "correct"
    assert rev["source_line"] and "12,412" in rev["source_line"]


def test_not_found(client):
    assert client.get("/runs/nope/summary").status_code == 404
    assert client.get("/runs/demo/filings/NOPE").status_code == 404
    assert client.get("/jobs/abc").status_code == 404


def test_extract_job_runs_heuristic_in_background(client):
    r = client.post("/extract", json={"ticker": "exwd", "run": "api_job"})
    assert r.status_code == 202
    job = client.get(f"/jobs/{r.json()['job_id']}").json()  # TestClient runs background tasks before returning
    assert job["status"] == "done", job
    assert job["provider"] == "heuristic" and job["ticker"] == "EXWD"
    assert client.get("/runs/api_job/summary").json()["accuracy"] == 1.0


def test_extract_validation(client, monkeypatch):
    assert client.post("/extract", json={"ticker": "EXWD", "run": "../evil"}).status_code == 400
    assert client.post("/extract", json={"ticker": "EXWD", "run": "x", "provider": "gpt"}).status_code == 400
    assert client.post("/extract", json={"ticker": "ZZZZ", "run": "x"}).status_code == 404
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/extract", json={"ticker": "EXWD", "run": "x", "provider": "anthropic"})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert client.post("/extract", json={"ticker": "EXWD", "run": "x", "provider": "openai"}).status_code == 400


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>finextract" in r.text and "prefers-color-scheme: dark" in r.text


def test_run_name_validation():
    assert valid_run_name("dev_gptoss_v1_verified")
    for bad in ["", "../x", ".hidden", "-x", "a/b", "a b", "x" * 101]:
        assert not valid_run_name(bad)
