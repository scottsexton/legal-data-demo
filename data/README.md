# Data

Raw data is **not** committed to git. `scripts/download_cap.py` downloads it to `data/cap/` on
your laptop and uploads it to the Unity Catalog Volume `/Volumes/legal_demo/raw/cap/`.

The download runs locally because Databricks Free Edition serverless compute blocks outbound
requests to static.case.law (HTTP 403 from its outbound filter).

## Source
- **Dataset:** Caselaw Access Project (Harvard Law School Library), https://case.law
- **Bulk files:** https://static.case.law
- **License:** CAP data is public domain / freely usable. Check the current terms at
  https://case.law before redistributing.
- **Downloaded:** 2026-11-22

## Slice
- **Reporter:** North Eastern Reporter, 3d series (`ne3d`), all volumes 1–130
- **Court:** Supreme Court of Indiana
- **Filter:** at least 5,000 characters (`analysis.char_count`). This removes one-line orders
  such as "Transfer denied". Without it, 91% of Indiana Supreme Court entries are those orders.
- **Result:** **459 cases**, **532 opinions** (majority, concurring, dissenting), decided
  2013-11-26 to 2019-08-22. Median opinion text is about 19k characters. 2 cases have almost no
  opinion text.
- **Size:** 14.4 MB of JSON

| Year | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|---|---|
| Cases | 2 | 116 | 83 | 67 | 78 | 68 | 45 |

## Volume layout
```
/Volumes/legal_demo/raw/cap/
├── manifest.jsonl          one line per case: id, name, decision_date, path, source_url, …
├── DOWNLOADED_ON
└── ne3d/{volume}/{file_name}.json   full CAP case JSON (casebody.opinions[].text, parties, judges, …)
```
