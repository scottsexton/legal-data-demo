from datetime import date

import pytest

from legal_demo.extract import (
    build_messages,
    drop_padded_day,
    merge_entities,
    normalize_date,
    parse_extraction,
    quote_is_verbatim,
)
from legal_demo.text import normalize_for_match

REPLY = """```json
{"entities": [
   {"name": "John Doe", "type": "Person", "role": "appellant", "description": "convicted of burglary"},
   {"name": "Marion Superior Court", "type": "tribunal", "role": "trial court"},
   {"name": "", "type": "person"}
 ],
 "events": [
   {"actor": "Marion Superior Court", "action": "convicted", "target": "John Doe",
    "date": "2017-03-03", "date_text": "March 3, 2017", "description": "Burglary conviction",
    "quote": "the Marion Superior Court convicted John Doe of burglary"},
   {"actor": "John Doe", "action": "appealed", "target": null, "date": "2017", "quote": "Doe appealed"},
   {"actor": "Court", "action": "", "date": "sometime"}
 ]}
```
Hope this helps!"""


def test_parse_extraction_cleans_and_filters():
    out = parse_extraction(REPLY)
    assert [e["name"] for e in out["entities"]] == ["John Doe", "Marion Superior Court"]
    assert out["entities"][0]["entity_type"] == "person"
    assert out["entities"][1]["entity_type"] == "other"
    assert len(out["events"]) == 2
    first, second = out["events"]
    assert first["event_date"] == date(2017, 3, 3) and first["date_text"] == "March 3, 2017"
    assert second["event_date"] is None and second["event_date_iso"] == "2017"


def test_parse_extraction_marks_clean_reply_not_repaired():
    assert parse_extraction(REPLY)["repaired"] is False


def test_parse_extraction_recovers_truncated_reply():
    truncated = (
        '{"entities": [{"name": "John Doe", "type": "person", "role": "appellant"}], '
        '"events": [{"actor": "John Doe", "action": "appealed", "quote": "Doe appealed"}, '
        '{"actor": "Court", "action": "affirmed", "quote": "We aff'
    )
    out = parse_extraction(truncated)
    assert out["repaired"] is True
    assert [e["name"] for e in out["entities"]] == ["John Doe"]
    assert [e["action"] for e in out["events"]] == ["appealed"]


def test_parse_extraction_recovers_when_cut_inside_entities():
    truncated = '{"entities": [{"name": "A B", "type": "person", "role": "x"}, {"name": "C'
    out = parse_extraction(truncated)
    assert [e["name"] for e in out["entities"]] == ["A B"] and out["events"] == []


def test_parse_extraction_rejects_non_json():
    with pytest.raises(ValueError):
        parse_extraction("Sorry, I can't help with that.")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2018-06-20", (date(2018, 6, 20), "2018-06-20")),
        ("2018-06", (None, "2018-06")),
        ("2018-02-30", (None, None)),
        ("June 2018", (None, None)),
        (None, (None, None)),
    ],
)
def test_normalize_date(value, expected):
    assert normalize_date(value) == expected


def test_quote_is_verbatim():
    source = normalize_for_match(
        "On March 3, 2017, the Marion Superior Court convicted John Doe of burglary. Doe appealed."
    )
    assert quote_is_verbatim("the Marion Superior Court  convicted John Doe", source)
    assert quote_is_verbatim("the Marion Superior Court ... of burglary", source)
    assert not quote_is_verbatim("the court acquitted John Doe", source)
    assert not quote_is_verbatim(None, source)


def test_merge_entities_dedupes_across_segments():
    seg1 = [{"name": "John Doe", "role": "appellant", "description": None, "entity_type": "person"}]
    seg2 = [
        {
            "name": "john doe",
            "role": "Appellant",
            "description": "burglar",
            "entity_type": "person",
        },
        {"name": "Loretta Rush", "role": "justice", "description": None, "entity_type": "person"},
    ]
    merged = merge_entities([seg1, seg2])
    assert len(merged) == 2
    doe = next(e for e in merged if e["name"] == "John Doe")
    assert doe["mention_count"] == 2 and doe["description"] == "burglar"


def test_build_messages():
    msgs = build_messages("Doe v. State", "2018-06-20", "TEXT HERE", 0, 2)
    assert msgs[0]["role"] == "system"
    assert "Segment 1 of 2" in msgs[1]["content"] and "TEXT HERE" in msgs[1]["content"]


@pytest.mark.parametrize(
    "iso, text, expected",
    [
        ("1999-01-01", "1999", (None, "1999")),
        ("2010-12-01", "December 2010", (None, "2010-12")),
        ("2009-01-01", "Ten years later", (None, "2009")),
        ("2014-08-01", "August 1, 2014", (date(2014, 8, 1), "2014-08-01")),
        ("2014-08-01", "the first of August", (date(2014, 8, 1), "2014-08-01")),
        ("2014-08-27", "August 27, 2014", (date(2014, 8, 27), "2014-08-27")),
        ("2013-01-01", None, (date(2013, 1, 1), "2013-01-01")),
    ],
)
def test_drop_padded_day(iso, text, expected):
    assert drop_padded_day(*normalize_date(iso), text) == expected
