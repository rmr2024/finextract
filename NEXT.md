# Next steps (updated 2026-11-01, Day 5)

## Done

- **Held-out test set** (JNJ WMT HD MCD ORCL, 44 labeled): `test5_gptoss_v1` complete at 50/50.

  | Test | Exact | Ungrounded | Confident-wrong |
  |---|---|---|---|
  | heuristic v2 | 59.1% | 0% | 29.7% |
  | gpt-oss v1 | 75.0% | 14.3% | 21.4% |
  | gpt-oss v1 + verify | **84.1%** | **0%** | 11.9% |

  Dev for comparison: 68.2%, 81.8% and 93.2%. On test, verify fixed 4 items and broke 0 (dev: 5 and
  0). See the README for why the gap exists.
- **Stage 3 part 1: service.**
  - SQLite store; `finextract import --run X`.
  - FastAPI endpoints: `/runs`, `/runs/{run}/summary`, `/runs/{run}/filings[/{id}]`, `POST /extract`
    as a background job, `/jobs/{id}`.
  - Dashboard at `/`; `finextract serve` binds 127.0.0.1.
  - Dockerfile, not built yet: Docker isn't installed here.
- **Operational note:** a run started with `Start-Process` from Claude's shell was killed twice. Runs
  launched as a tracked background job, or from your own terminal, finish normally.

## Stage 3 part 2

1. **Async batch jobs.** Today, `POST /extract` handles one ticker per job and runs in FastAPI's
   in-process background tasks, so jobs die with the server, and two jobs on the same run can race.
   - Add `POST /batch {tickers[], run, provider}` with a persistent queue: the `jobs` table as the
     queue plus one worker thread or process.
   - Allow one job per run at a time, retry failed fields with `--resume`, and record per-ticker
     progress in `/jobs/{id}`.
   - Treat the provider's daily limit as "paused until X", not "failed".
2. **Caching.**
   - Key LLM responses by (prompt_hash, model, filing, field, chunk ids) in SQLite, so re-runs and
     re-scoring cost no tokens.
   - Cache BM25 indexes per filing, since they're rebuilt for every run.
   - Add ETag or Cache-Control headers on the summary endpoints.
3. **CI for Docker.**
   - A GitHub Actions job runs `docker build`, then starts the container and smoke-tests `/runs` and
     `/` with curl.
   - Optionally scan the image (Trivy) and confirm no `.env` or data files ended up in it.
4. Smaller items:
   - auth, or keep localhost-only;
   - pagination on `/runs/{run}/filings`;
   - re-import a run automatically when its jsonl changes;
   - handle `httpx` vs `httpx2` for Starlette's TestClient, which warns about httpx deprecation.

## Later (from earlier stages)

- `dev_gptoss_v2` (prompt v2: cash excludes restricted cash), ~125k tokens.
- Retrieval fixes for the 2 missing fields on each of dev and test.
- More label QA: 15 checked so far, 0 mismatches.

## Commands

```powershell
pip install -e ".[api]"
finextract import --run test5_gptoss_v1_verified
finextract serve        # http://127.0.0.1:8000/
```
