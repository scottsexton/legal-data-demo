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
- [x] **Bronze:** `bronze.documents_raw` holds each JSON file as loaded (`spark.read.text(..., wholetext=True)`). `bronze.extractions_raw` keeps every raw LLM reply, so prompts can change without losing history.
- [x] **Silver:** `silver.documents` has 459 rows: `doc_id, case_name, court, decision_date, citation, judges, parties, attorneys, opinion_types, full_text, source_url`, and more.
- [x] **Silver:** `silver.chunks` has 4,723 chunks (`chunk_id, doc_id, chunk_index, text`) of about 3,000 characters with 400 characters of overlap. Change Data Feed is on, and it's loaded with MERGE so re-runs only touch changed chunks.
- [x] **Gold (the "people, times, actions" layer):** Python extraction with a JSON prompt (`src/legal_demo/extract.py`, prompt `v2`), run on long opinions in segments of 24,000 characters:
  - `gold.entities`: `doc_id, name, entity_type, role, description, mentions`
  - `gold.events`: `event_id, doc_id, actor, action, target, event_date, date_text, evidence_quote, quote_verified`
  - `quote_verified` is true when the quote appears word for word in the opinion.
  - Full run: 665 segments, 0 failed calls, 2h10m. 7,906 events (84% of quotes verified, 44% with a full date, 59% with at least a year) and 7,663 entities; 457 of 459 cases have events.
  - If the model pads a partial date ("1999" → 1999-01-01), the parser keeps only the year or month.
- [x] **Vector Search:** endpoint `legal-demo-vs` and a Delta Sync index `silver.chunks_index` with managed `databricks-gte-large-en` embeddings. The first build of all 4,723 chunks took over an hour on Free Edition; later syncs only embed changed chunks.
- [x] **Validation notebook:** `05_validate.py` checks row counts, uniqueness, orphan chunks, extraction coverage and the share of verified quotes, and prints 10 random events to spot-check.
- [x] **Databricks Job:** `legal-data-pipeline` in `databricks.yml`: transform → (extract ‖ index) → validate. Deploy with `scripts/deploy.sh dev`, then run with `databricks bundle run -t dev legal_pipeline`.

**What changed during Phase 4**
- **Chat model is now `databricks-qwen3-next-80b-a3b-instruct`.** On Free Edition, Llama 3.3 70B was throttled to 200–300s per segment, which would mean about 7 hours for the full run. On 4 real segments at once, Qwen took ~20s and found more events (86% of quotes verbatim, 76% dated); Llama took 91s. Llama 4 Maverick's quotes were only 35% verbatim, and GPT-OSS 120B returned invalid JSON.
- **Extraction is slower under sustained load:** each call took ~54s on average, not ~20s as in the benchmark. The extract step skips segments already saved, so a run that times out resumes where it stopped.
- **Cut-off replies are recovered:** if a reply hits the output limit, the parser keeps every complete entity and event.
- **Shared code loads from a Volume:** notebooks on Free Edition often got `[Errno 5] Input/output error` reading bundle files right after a deploy. `scripts/push_code.sh` copies `src/legal_demo` to `/Volumes/legal_demo/raw/code/<target>/`, and the notebooks import from there.

---

## Phase 5: Streamlit App ✅
Deployed as the Databricks App `legal-demo` (prod, deployed by GitHub Actions): https://legal-demo-7474653380156089.aws.databricksapps.com. Dev copy: `legal-demo-dev`.
- [x] **Login:** Databricks workspace SSO. Only workspace users with access to the app can open it; the sidebar shows who is signed in (from the `X-Forwarded-Email` header).
- [x] **Browse:** all 459 cases, filtered by name/docket, year, opinion type and author. Author strings are noisy OCR (about 70 spellings), so `author_names()` maps them to the 7 justices plus "Per curiam". Selecting a case opens a dialog with its event timeline (✓ = verbatim quote), people, full text and a case.law link.
- [x] **Search:** *Meaning* (hybrid Vector Search), *Exact words* (SQL, with highlighted snippets) and *People* (`gold.entities`). About 1 second each.
- [x] **Ask:** RAG chat over up to 6 cases. Each case's source combines the best passages (hybrid search) with its extracted events; a year in the question reserves up to 3 of the 6 slots for cases with events dated that year. Answers stream (first words in about 2s) and cite cases as `[C1: Case Name]`, with a Sources list. "Ask about this case" limits the chat to one case.
- [x] **Code:** `app/app.py` (UI), `app/backend.py` (SQL Statement API, Vector Search and the chat model through the SDK, no extra clients), `app/rag.py` (prompt and sources, unit tested), `app/display.py` (escaping and highlighting, unit tested).
- [x] **Permissions:** the app runs as its own service principal. `databricks.yml` grants it CAN_USE on the warehouse, CAN_QUERY on both model endpoints and SELECT on the three tables and the Vector Search index.
- [ ] **App users group:** to share the demo, add people to a group and give that group CAN_USE on the app.

**Run it**
```bash
uv run streamlit run app/app.py               # locally, with your Databricks CLI login
scripts/deploy.sh dev && databricks bundle run -t dev legal_app   # deploy and (re)start the dev app
```

---

## Phase 6: CI/CD ✅
- [x] **CI** (`.github/workflows/ci.yml`): every pull request and push to `main` runs `ruff check`, `ruff format --check` and `pytest` with a cached, locked `uv` environment. A newer run on the same branch cancels the older one.
- [x] **Deploy** (`.github/workflows/deploy.yml`): after CI passes on `main` (or when run by hand), it authenticates as the `legal-data-demo-ci` service principal and then:
  1. validates the bundle (`databricks bundle validate -t prod`);
  2. copies the shared code to the Volume and deploys the bundle (`scripts/deploy.sh prod`);
  3. deploys the app's code and starts it (`databricks bundle run -t prod legal_app`);
  4. fails unless the app is running and its deployment succeeded (`scripts/check_app.sh`).
- [x] **Prod runs as the service principal:** the job, the app and the bundle files are owned by `legal-data-demo-ci`; admins can manage them. `scripts/grant_ci.sh` gives it CAN_MANAGE on the warehouse and Vector Search endpoint, MANAGE on the catalog (so a deploy can grant the app its access) and ownership of the index.
- [x] **Dev and prod apps:** `legal-demo` (prod) and `legal-demo-dev` (dev, deployed from your laptop) are separate apps over the same data. `bundle validate -t prod` fails locally because only the service principal may deploy prod.
- [x] **Dependabot** (`.github/dependabot.yml`): weekly update PRs for GitHub Actions and Python packages.
- [ ] **Branch protection:** not available on a private repo on the free GitHub plan. Make the repo public or upgrade to require CI before merging.
- Both targets share the `legal_demo` catalog, so the data is loaded once (the extraction took over 2 hours).
- [x] **Prod pipeline runs as the service principal.** Only a Vector Search index's owner can sync it, so `scripts/grant_ci.sh` makes the service principal the owner of `silver.chunks_index`. The index's internal update pipeline still runs as its creator (you), so the script also grants that identity MODIFY on the `silver` schema (MODIFY can't be granted on an index directly). The dev job skips the sync with a message (your login isn't the owner); the prod job keeps the index in sync.

---

## Later Phases (After Data Is Loaded)
- **Phase 7, Demo polish:** seed questions, an evaluation set of 20 Q&A pairs, and a short README with screenshots.

## Decisions
- ✅ **Dataset:** Indiana Supreme Court, N.E.3d, about 500 cases (fallback: Illinois Supreme Court, `ill-2d`).
- ✅ **Workspace:** Databricks Free Edition (account created).
- ✅ **Hugging Face:** account created. It's optional now, since we download from `static.case.law` directly.
- ✅ **GitHub repo:** https://github.com/scottsexton/legal-data-demo
- ✅ **App UI:** Streamlit
- ✅ **Chat model:** `databricks-qwen3-next-80b-a3b-instruct` (switched from Llama 3.3 70B in Phase 4; set in `databricks.yml` and easy to change).
- ✅ **Embedding model:** `databricks-gte-large-en`
