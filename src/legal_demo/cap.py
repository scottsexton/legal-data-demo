"""Helpers for the Caselaw Access Project (CAP) static bulk data at static.case.law.

Layout:
    {BASE}/{reporter}/{volume}/CasesMetadata.json   -> list of case metadata dicts
    {BASE}/{reporter}/{volume}/cases/{file_name}.json -> one case, with full text
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

BASE_URL = "https://static.case.law"

# Default demo slice: Indiana Supreme Court opinions in the North Eastern Reporter, 3d series.
DEFAULT_REPORTER = "ne3d"
DEFAULT_COURT = "Supreme Court of Indiana"


def cases_metadata_url(reporter: str, volume: int | str) -> str:
    return f"{BASE_URL}/{reporter}/{volume}/CasesMetadata.json"


def case_url(reporter: str, volume: int | str, file_name: str) -> str:
    return f"{BASE_URL}/{reporter}/{volume}/cases/{file_name}.json"


def filter_by_court(cases: Iterable[dict], court_name: str = DEFAULT_COURT) -> Iterator[dict]:
    """Yield only the cases decided by `court_name`."""
    for case in cases:
        if (case.get("court") or {}).get("name") == court_name:
            yield case
