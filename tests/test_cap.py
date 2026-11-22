from legal_demo.cap import case_url, cases_metadata_url, filter_by_court


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
