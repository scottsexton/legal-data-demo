# Legal Data Demo

A demo app where a signed-in user can browse and search Indiana Supreme Court opinions and ask an
LLM questions about the people, dates and actions in them.

**Stack:** Python 3.12 · Databricks (Unity Catalog, Vector Search, Foundation Model APIs, Apps) ·
Streamlit · GitHub Actions

See [docs/PLAN.md](docs/PLAN.md) for the full plan.

## Layout
```
databricks.yml      Databricks Asset Bundle (jobs + app deployment)
src/legal_demo/     shared Python (CAP download helpers, parsing, prompts)
notebooks/          Databricks pipeline notebooks (ingest → transform → extract → index)
app/                Streamlit app, deployed as a Databricks App
tests/              pytest tests
data/               notes on the dataset (raw data is not committed)
```

## Local setup
If the repo is inside an iCloud-synced folder (such as `~/Documents`), iCloud sets the macOS
"hidden" flag on `.venv`, and Python then skips its `.pth` files, which breaks
`import legal_demo`. Keep the environment in a folder iCloud ignores:
```bash
mkdir .venv.nosync && ln -s .venv.nosync .venv
```

```bash
uv sync --group dev        # creates .venv with Python 3.12 and all dependencies
uv run pytest              # run tests
uv run ruff check .        # lint
uv run streamlit run app/app.py   # run the app locally
```

## Data
```bash
uv run python scripts/download_cap.py --upload   # download 459 Indiana Supreme Court opinions, upload to UC
```
See [data/README.md](data/README.md) for the source, filter and layout.

## Pipeline
```bash
scripts/deploy.sh dev                                  # copy src/legal_demo to a UC Volume, deploy the bundle
databricks bundle run -t dev legal_pipeline            # transform → extract + index → validate
databricks bundle run -t dev legal_pipeline --params max_docs=5   # quick test on 5 cases
```
Use `scripts/deploy.sh` rather than `databricks bundle deploy`: the notebooks import the shared
code from a Volume (see [notebooks/README.md](notebooks/README.md)). Pushes to `main` deploy the
`prod` target from GitHub Actions after CI passes.
