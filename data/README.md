# Data

Raw data is **not** committed to git. The ingest notebook (`notebooks/01_ingest.py`) downloads it
to the Unity Catalog Volume `/Volumes/legal_demo/raw/cap/`.

## Source
- **Dataset:** Caselaw Access Project (Harvard Law School Library), https://case.law
- **Bulk files:** https://static.case.law
- **Slice:** Indiana Supreme Court opinions in the North Eastern Reporter, 3d series (`ne3d`),
  latest ~50 volumes, about 500 cases (roughly 2016–2018)
- **License:** CAP data is public domain / freely usable. Check the current terms at https://case.law before redistributing.
- **Downloaded:** _fill in the date when ingest first runs_
