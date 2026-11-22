# Notebooks

Pipeline notebooks, run as one Databricks Job (`legal-data-pipeline` in `databricks.yml`):

1. `02_transform.py`: Volume JSON → bronze → silver documents and chunks
2. `03_extract.py`: LLM extraction of people, dates and actions into gold tables
3. `04_index.py`: Vector Search index on chunks (runs alongside extraction)
4. `05_validate.py`: counts, consistency checks and a sample of events to spot-check

Step 1 of the pipeline (download) runs on your laptop with `scripts/download_cap.py`, because
Free Edition serverless compute can't reach static.case.law. See `data/README.md`.

The notebooks import `legal_demo` from `/Volumes/<catalog>/raw/code/<target>/` (job parameter
`code_path`), not from the bundle files. `scripts/deploy.sh` copies it there before deploying.
