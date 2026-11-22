# Notebooks

Pipeline notebooks, run as one Databricks Job (Phase 4):

1. `01_ingest.py`: download the CAP slice into the UC Volume (Phase 3)
2. `02_transform.py`: bronze → silver documents and chunks
3. `03_extract.py`: LLM extraction of people, dates and actions into gold tables
4. `04_index.py`: Vector Search index on chunks
