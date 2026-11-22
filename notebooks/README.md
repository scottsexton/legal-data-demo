# Notebooks

Pipeline notebooks, run as one Databricks Job (Phase 4):

1. `02_transform.py`: Volume JSON → bronze → silver documents and chunks
2. `03_extract.py`: LLM extraction of people, dates and actions into gold tables
3. `04_index.py`: Vector Search index on chunks

Step 1 of the pipeline (download) runs on your laptop with `scripts/download_cap.py`, because
Free Edition serverless compute can't reach static.case.law. See `data/README.md`.
