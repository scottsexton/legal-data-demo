import json

from legal_demo.cap import case_url, cases_metadata_url, download_cases, filter_by_court


def test_urls():
    assert cases_metadata_url("ne3d", 100) == "https://static.case.law/ne3d/100/CasesMetadata.json"
    assert case_url("ne3d", 100, "0001-01") == "https://static.case.law/ne3d/100/cases/0001-01.json"


def test_filter_by_court_keeps_only_indiana_supreme_court():
    cases = [
        {"id": 1, "court": {"name": "Supreme Court of Indiana"}},
        {"id": 2, "court": {"name": "Supreme Court of Ohio"}},
        {"id": 3, "court": {"name": "Court of Appeals of Indiana"}},
        {"id": 4},
    ]
    assert [c["id"] for c in filter_by_court(cases)] == [1]


def test_filter_by_court_drops_short_orders():
    court = {"name": "Supreme Court of Indiana"}
    cases = [
        {"id": 1, "court": court, "analysis": {"char_count": 300}},  # "Transfer denied."
        {"id": 2, "court": court, "analysis": {"char_count": 25000}},
        {"id": 3, "court": court},  # no analysis → treated as 0 chars
    ]
    assert [c["id"] for c in filter_by_court(cases, min_chars=5000)] == [2]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Volume 2 is missing (404); volume 1 has one Indiana and one Ohio case."""

    def __init__(self):
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        if url.endswith("/2/CasesMetadata.json"):
            return FakeResponse(404)
        if url.endswith("/1/CasesMetadata.json"):
            return FakeResponse(
                payload=[
                    {
                        "id": 10,
                        "file_name": "0001-01",
                        "decision_date": "2018-01-01",
                        "court": {"name": "Supreme Court of Indiana"},
                    },
                    {"id": 11, "file_name": "0009-01", "court": {"name": "Supreme Court of Ohio"}},
                ]
            )
        return FakeResponse(content=b'{"id": 10}')


def test_download_cases_filters_skips_missing_volumes_and_resumes(tmp_path):
    session = FakeSession()
    kwargs = dict(
        volumes=[2, 1], max_cases=10, min_chars=0, delay_s=0, session=session, log=lambda *_: None
    )

    result = download_cases(tmp_path, **kwargs)
    assert result.volumes_missing == [2]
    assert result.cases_saved == 1
    assert (tmp_path / "ne3d" / "1" / "0001-01.json").read_bytes() == b'{"id": 10}'
    rows = [json.loads(line) for line in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == [10]
    assert rows[0]["path"] == "ne3d/1/0001-01.json"

    # Second run keeps the existing file instead of downloading it again.
    again = download_cases(tmp_path, **kwargs)
    assert again.cases_saved == 0 and again.cases_skipped_existing == 1


def test_download_cases_respects_max_cases(tmp_path):
    result = download_cases(
        tmp_path, volumes=[1], max_cases=0, delay_s=0, session=FakeSession(), log=lambda *_: None
    )
    assert result.volumes_checked == 0 and result.cases_saved == 0
