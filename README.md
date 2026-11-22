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
```bash
uv sync --group dev        # creates .venv with Python 3.12 and all dependencies
uv run pytest              # run tests
uv run ruff check .        # lint
uv run streamlit run app/app.py   # run the app locally
```
