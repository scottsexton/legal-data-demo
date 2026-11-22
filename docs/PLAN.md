# Legal Document Q&A Demo: Project Plan

## Goal
A signed-in user can:
1. **List and search** documents in a legal test dataset.
2. **Ask an LLM questions** about the **people, dates and actions** in those documents (for example: "Who was the appellant in the 1998 cases, and what did the court decide?").

**Stack:** Python, Databricks (storage, compute, LLM, hosting), GitHub (source control and CI/CD).

---

## Recommended Test Dataset

| Dataset | What it is | License | Fit for "people / times / actions" |
|---|---|---|---|
| **Caselaw Access Project (CAP)** ⭐ | About 6.7M US court opinions (Harvard Law), released to the public in 2024. Bulk JSON at `static.case.law`, also on Hugging Face as `free-law/Caselaw_Access_Project` | Public domain / CC0 | **Best.** Opinions name parties, judges and attorneys, give filing and decision dates, and describe actions (filed, appealed, reversed, affirmed). |
| CourtListener bulk data (Free Law Project) | Opinions, dockets, oral-argument audio | Free / public domain | Very good, but the files are large. The API needs a free token. |
| CUAD (Atticus Project) | 510 commercial contracts with 41 expert-labeled clause types | CC BY 4.0 | Good for parties, effective dates and obligations. It's contracts, not cases. |
| Pile of Law | 256GB mixed legal corpus | Mixed (mostly CC BY-NC-SA) | Too big and mixed for a demo. |

**Chosen slice: all 459 full Indiana Supreme Court opinions in the North Eastern Reporter, 3d series (N.E.3d), decided 2013–2019.** (Downloaded in Phase 3. Details in `data/README.md`.)
- **Why Indiana:** the court sits in Indianapolis, which suits the audience. These are modern opinions, with a median of about 19k characters, and clear parties, dates and outcomes.
- **Why N.E.3d:** CAP's own Indiana reporter (`ind`) stops in 1981. Modern Indiana cases are only in the regional N.E.2d/N.E.3d reporters, which mix in Ohio, New York, Illinois and Massachusetts. We filter on `court.name == "Supreme Court of Indiana"` using each volume's `CasesMetadata.json`.
- **Volume:** 91% of Indiana Supreme Court entries are one-line orders ("Transfer denied"), so we also require `analysis.char_count >= 5000`. Scanning all 130 volumes gives 459 real opinions. Add `Court of Appeals of Indiana` if you need more.
- **Fallback (Illinois):** Illinois Supreme Court, `ill-2d`, latest volumes (about 230–242, 2008–2011). That reporter is Illinois-only, so no filtering is needed, but its opinions are longer (about 60k characters).

**CAP layout (verified):** `https://static.case.law/{reporter}/{volume}/CasesMetadata.json` lists the cases in a volume. Each case's full text is at `.../{volume}/cases/{file_name}.json`, and a whole volume is at `{reporter}/{volume}.zip`.

---

## Target Architecture

```
GitHub repo ──(GitHub Actions + Databricks Asset Bundles)──► Databricks workspace
                                                              │
  CAP JSON ─► UC Volume (raw) ─► bronze.documents_raw         │
                               ─► silver.documents (clean text, metadata)
                               ─► silver.chunks (text chunks)
                               ─► gold.entities  (people / orgs / roles)
                               ─► gold.events    (who, did what, when, doc_id)
                               ─► Vector Search index on silver.chunks
                                                              │
  Databricks App (Python: Streamlit or Gradio) ◄──────────────┘
    • Login: built-in Databricks workspace SSO (OAuth)
    • List / search: SQL Warehouse queries + vector search
    • Q&A: RAG over chunks + structured events → Foundation Model API
```

---

## Phase 0: Accounts & Prerequisites
- [ ] **Databricks workspace.** The *Databricks Free Edition* is enough for a demo. It includes serverless compute, Unity Catalog, Apps, Vector Search and Foundation Model APIs, with usage limits. Use a trial or paid workspace if you hit those limits. *Check the current Free Edition feature list before you start.*
- [ ] **GitHub account**, plus a new repo (for example `legal-data-demo`).
- [ ] **Local tools:** Python 3.11+, `uv` or `pip`, `git`, `gh` CLI, and the **Databricks CLI** (v0.2xx+, which is needed for bundles).
- [ ] **Hugging Face account.** Optional; it makes dataset downloads easier.

## Phase 1: Repo & Local Environment
- [ ] `git init`, add `.gitignore` (`.env`, `.databricks/`, `data/`, `__pycache__/`).
- [ ] Create the project layout:
  ```
  legal-data-demo/
  ├── databricks.yml            # Asset Bundle: jobs, app, targets (dev/prod)
  ├── pyproject.toml
  ├── src/legal_demo/           # shared Python (parsing, chunking, prompts)
  ├── notebooks/                # 01_ingest, 02_transform, 03_extract, 04_index
  ├── app/                      # Databricks App (app.py, app.yaml, requirements.txt)
  ├── tests/
  └── .github/workflows/        # ci.yml (lint/test), deploy.yml (bundle deploy)
  ```
- [x] Virtual env created with `uv sync --group dev` (Python 3.12).
- [x] Pushed to https://github.com/scottsexton/legal-data-demo. CI (lint, format, tests) passes.

## Phase 2: Connect Dependencies
- [x] **Databricks CLI auth:** `DEFAULT` profile created for `https://dbc-eade77b4-fdf2.cloud.databricks.com`.
- [x] Checked with `databricks current-user me`: workspace admin. Unity Catalog is on, with the default catalog `workspace`. The `Serverless Starter Warehouse` is available. Vector Search and Apps APIs respond, with nothing created yet.
- [ ] **Databricks Git folder (optional):** link the GitHub repo in the workspace (Workspace → Create → Git folder) if you want to edit notebooks in the workspace UI. Bundle deploys don't need it.
- [x] **CI/CD auth:** created the service principal `legal-data-demo-ci` (app ID `da061def-…`) with an OAuth secret that expires **2028-11-21**. `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` are GitHub Actions secrets. `.github/workflows/deploy.yml` deploys the `prod` target after CI passes on `main` (or when run manually). Prod lives in the service principal's own workspace folder, runs as it, and the `admins` group has CAN_MANAGE.
- [x] `databricks bundle validate` and `databricks bundle deploy -t dev` both succeed. The host and model variables are in `databricks.yml`.
- [x] **LLM access:** 8 chat and 3 embedding endpoints are ready. `scripts/smoke_test_llm.py` tests them. No Claude models on Free Edition.
  - **Chat:** `databricks-meta-llama-3-3-70b-instruct`. It found all 4 events in the test passage as valid JSON (3.5s). Fastest alternative: `databricks-qwen3-next-80b-a3b-instruct` (1.2s, 3 events). `qwen35-122b` returned invalid JSON.
  - **Embeddings:** `databricks-gte-large-en`, 1024 dimensions.
- [x] **Unity Catalog permissions:** Free Edition *does* allow `CREATE CATALOG`, so we use a dedicated `legal_demo` catalog.

## Phase 3: Download the Test Dataset
- [x] **Serverless internet check:** Free Edition serverless can reach PyPI but gets **HTTP 403** from static.case.law, so the download runs on the laptop instead of in a notebook.
- [x] `scripts/download_cap.py` (logic in `src/legal_demo/cap.py`, with tests):
  1. Goes through N.E.3d volumes 130 → 1 and fetches each `CasesMetadata.json` (skipping any that return 404).
  2. Keeps `court.name == "Supreme Court of Indiana"` and `analysis.char_count >= 5000`.
  3. Fetches each case JSON with retries and a 0.2s delay, and resumes if re-run.
  4. Writes `manifest.jsonl` and `DOWNLOADED_ON`, then uploads everything with `--upload` / `--upload-only` (Databricks Files API).
- [x] Uploaded to `/Volumes/legal_demo/raw/cap/`: 461 files, checked with SQL `read_files` (459 unique cases, 532 opinions).
- [x] Source, license, filter and download date recorded in `data/README.md`.

## Phase 4: Create & Load the Data Storage
- [x] **Unity Catalog objects:** done early in Phase 3. See `sql/00_setup.sql`: catalog `legal_demo`, schemas `raw`/`bronze`/`silver`/`gold`, Volume `raw.cap`, and grants to the CI service principal.
- [ ] **Bronze:** `bronze.documents_raw` holds the JSON as loaded (Auto Loader or `read_files`).
- [ ] **Silver:** `silver.documents` has `doc_id, case_name, court, decision_date, citation, judges, parties, full_text, source_url`.
- [ ] **Silver:** `silver.chunks` has `chunk_id, doc_id, chunk_index, text`, with about 1,000-token chunks that overlap. Turn on Change Data Feed.
- [ ] **Gold (the "people, times, actions" layer):** run LLM extraction with `ai_query()` or a Python UDF and a JSON schema:
  - `gold.entities`: `doc_id, name, type (person/org), role (judge/plaintiff/defendant/attorney)`
  - `gold.events`: `doc_id, actor, action, target, event_date, evidence_quote`
- [ ] **Vector Search:** create an endpoint and a Delta Sync index on `silver.chunks` using the embedding endpoint.
- [ ] **Validation notebook:** row counts, null checks, and spot-checks of 10 extracted events against the source text.
- [ ] Package notebooks 01–04 as one **Databricks Job** in `databricks.yml` so the whole pipeline re-runs from one command.

---

## Later Phases (After Data Is Loaded)
- **Phase 5, App:** a Databricks App (Streamlit) with three tabs: *Browse* (paged list and filters), *Search* (keyword + semantic), *Ask* (RAG chat that cites `doc_id`s and pulls from `gold.events` for "who / when / what" questions). Workspace SSO handles login, and you can limit access to an app-users group.
- **Phase 6, CI/CD:** GitHub Actions runs `ruff` and `pytest` on each PR, and `databricks bundle deploy -t prod` on merge to `main`.
- **Phase 7, Demo polish:** seed questions, an evaluation set of 20 Q&A pairs, and a short README with screenshots.

## Decisions
- ✅ **Dataset:** Indiana Supreme Court, N.E.3d, about 500 cases (fallback: Illinois Supreme Court, `ill-2d`).
- ✅ **Workspace:** Databricks Free Edition (account created).
- ✅ **Hugging Face:** account created. It's optional now, since we download from `static.case.law` directly.
- ✅ **GitHub repo:** https://github.com/scottsexton/legal-data-demo
- ✅ **App UI:** Streamlit
- ✅ **Chat model:** `databricks-meta-llama-3-3-70b-instruct` (set in `databricks.yml` and easy to change).
- ✅ **Embedding model:** `databricks-gte-large-en`
