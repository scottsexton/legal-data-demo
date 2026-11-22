"""Helpers for the Caselaw Access Project (CAP) static bulk data at static.case.law.

Layout:
    {BASE}/{reporter}/{volume}/CasesMetadata.json      -> list of case metadata dicts
    {BASE}/{reporter}/{volume}/cases/{file_name}.json  -> one case, with full text

Note: Databricks Free Edition serverless compute can't reach static.case.law (its outbound
filter returns 403), so downloads run locally via scripts/download_cap.py.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://static.case.law"

# Default demo slice: Indiana Supreme Court opinions in the North Eastern Reporter, 3d series.
DEFAULT_REPORTER = "ne3d"
DEFAULT_COURT = "Supreme Court of Indiana"
USER_AGENT = "legal-data-demo/0.1 (research demo; python-requests)"


def cases_metadata_url(reporter: str, volume: int | str) -> str:
    return f"{BASE_URL}/{reporter}/{volume}/CasesMetadata.json"


def case_url(reporter: str, volume: int | str, file_name: str) -> str:
    return f"{BASE_URL}/{reporter}/{volume}/cases/{file_name}.json"


# Most Indiana Supreme Court entries in N.E.3d are one-line orders ("Transfer denied.") with no
# opinion text. Requiring this many characters keeps only real opinions.
DEFAULT_MIN_CHARS = 5000


def filter_by_court(
    cases: Iterable[dict], court_name: str = DEFAULT_COURT, min_chars: int = 0
) -> Iterator[dict]:
    """Yield cases decided by `court_name` whose text is at least `min_chars` long."""
    for case in cases:
        if (case.get("court") or {}).get("name") != court_name:
            continue
        if (case.get("analysis") or {}).get("char_count", 0) < min_chars:
            continue
        yield case


def make_session() -> requests.Session:
    """HTTP session with retries and backoff for transient errors."""
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = USER_AGENT
    return session


@dataclass
class DownloadResult:
    volumes_checked: int = 0
    volumes_missing: list[int] = field(default_factory=list)
    cases_saved: int = 0
    cases_skipped_existing: int = 0


def download_cases(
    out_dir: Path,
    *,
    reporter: str = DEFAULT_REPORTER,
    court_name: str = DEFAULT_COURT,
    min_chars: int = DEFAULT_MIN_CHARS,
    volumes: Iterable[int],
    max_cases: int,
    delay_s: float = 0.2,
    session: requests.Session | None = None,
    log=print,
) -> DownloadResult:
    """Download cases from `court_name` into out_dir/{reporter}/{volume}/{file_name}.json.

    Volumes are visited in the order given (pass them newest-first to get the most recent
    cases). Files that already exist are kept, so re-running resumes where it left off.
    A manifest (one JSON line of metadata per saved case) is written to out_dir/manifest.jsonl.
    """
    session = session or make_session()
    result = DownloadResult()
    manifest: list[dict] = []

    for volume in volumes:
        if len(manifest) >= max_cases:
            break
        result.volumes_checked += 1
        resp = session.get(cases_metadata_url(reporter, volume), timeout=30)
        if resp.status_code == 404:
            result.volumes_missing.append(volume)
            continue
        resp.raise_for_status()
        matches = list(filter_by_court(resp.json(), court_name, min_chars))
        log(f"{reporter} vol {volume}: {len(matches)} matching cases")
        time.sleep(delay_s)

        for meta in matches:
            if len(manifest) >= max_cases:
                break
            path = out_dir / reporter / str(volume) / f"{meta['file_name']}.json"
            if path.exists():
                result.cases_skipped_existing += 1
            else:
                case_resp = session.get(case_url(reporter, volume, meta["file_name"]), timeout=60)
                case_resp.raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(case_resp.content)
                result.cases_saved += 1
                time.sleep(delay_s)
            manifest.append(manifest_row(meta, reporter, volume, path.relative_to(out_dir)))

    write_manifest(out_dir / "manifest.jsonl", manifest)
    return result


def manifest_row(meta: dict, reporter: str, volume: int | str, rel_path: Path) -> dict:
    return {
        "id": meta.get("id"),
        "name_abbreviation": meta.get("name_abbreviation"),
        "decision_date": meta.get("decision_date"),
        "court": (meta.get("court") or {}).get("name"),
        "char_count": (meta.get("analysis") or {}).get("char_count"),
        "reporter": reporter,
        "volume": str(volume),
        "file_name": meta.get("file_name"),
        "path": rel_path.as_posix(),
        "source_url": case_url(reporter, volume, meta["file_name"]),
    }


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
