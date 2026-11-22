from datetime import date

import pytest

from legal_demo.text import (
    build_full_text,
    case_to_document,
    chunk_text,
    document_to_chunks,
    normalize_for_match,
    parse_date,
)

CASE = {
    "id": 4288888,
    "name": "Dennis GARNER, Appellant v. Gregory S. KEMPF, Appellee",
    "name_abbreviation": "Garner v. Kempf",
    "decision_date": "2018-03-26",
    "docket_number": "No. 82S01",
    "file_name": "1091-01",
    "citations": [{"type": "official", "cite": "93 N.E.3d 1091"}],
    "court": {"name": "Supreme Court of Indiana"},
    "casebody": {
        "head_matter": "Dennis GARNER v. KEMPF\nSupreme Court of Indiana.",
        "parties": ["Dennis GARNER, Appellant"],
        "judges": [],
        "attorneys": [],
        "opinions": [
            {"type": "majority", "author": "Slaughter, J.", "text": "We reverse."},
            {"type": "dissent", "author": None, "text": "I dissent."},
            {"type": "concurrence", "author": "Rush", "text": ""},
        ],
    },
}


def test_parse_date():
    assert parse_date("2018-03-26") == date(2018, 3, 26)
    assert parse_date("2018-03") is None
    assert parse_date(None) is None


def test_build_full_text_labels_opinions_and_skips_empty():
    text = build_full_text(CASE)
    assert text.startswith("Dennis GARNER v. KEMPF")
    assert "--- MAJORITY OPINION (Slaughter, J.) ---\nWe reverse." in text
    assert "--- DISSENT OPINION ---\nI dissent." in text
    assert "CONCURRENCE" not in text


def test_case_to_document():
    doc = case_to_document(CASE, "ne3d", "93", "/Volumes/x/ne3d/93/1091-01.json")
    assert doc["doc_id"] == "4288888"
    assert doc["citation"] == "93 N.E.3d 1091"
    assert doc["decision_date"] == date(2018, 3, 26)
    assert doc["opinion_types"] == ["majority", "dissent", "concurrence"]
    assert doc["opinion_authors"] == ["Slaughter, J.", "Rush"]
    assert doc["source_url"] == "https://static.case.law/ne3d/93/cases/1091-01.json"
    assert doc["char_count"] == len(doc["full_text"])


def test_chunk_text_respects_size_covers_text_and_overlaps():
    paragraphs = [f"Paragraph {i} " + "word " * 60 for i in range(40)]
    chunks = chunk_text("\n".join(paragraphs), max_chars=1000, overlap=200)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    for p in paragraphs:
        assert any(p.strip() in c for c in chunks)
    # The start of each chunk repeats the end of the previous one.
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.split("\n")[0] in prev


def test_chunk_text_splits_one_huge_paragraph():
    chunks = chunk_text("x" * 50 + " " + "word " * 2000, max_chars=500, overlap=50)
    assert all(len(c) <= 500 for c in chunks)


def test_chunk_text_rejects_large_overlap():
    with pytest.raises(ValueError):
        chunk_text("abc", max_chars=100, overlap=60)


def test_document_to_chunks_prefixes_case_header():
    doc = case_to_document(CASE, "ne3d", "93", "f")
    chunks = document_to_chunks(doc)
    assert chunks[0]["chunk_id"] == "4288888-0000"
    assert chunks[0]["text"].startswith("Garner v. Kempf (2018-03-26)\n")


def test_normalize_for_match():
    assert normalize_for_match("The  Court’s\nruling") == "the court's ruling"
