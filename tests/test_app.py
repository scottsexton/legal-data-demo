"""Tests for the app's pure helpers (app/rag.py, app/display.py, SQL helpers in app/backend.py)."""

import pytest
from backend import Backend, _convert, _param, in_list
from display import author_names, cite_links, escape_md, highlight, html_url, tidy_snippet
from rag import (
    MAX_SOURCES,
    PASSAGES_PER_SOURCE,
    YEAR_SOURCES,
    build_messages,
    build_sources,
    cited_labels,
    extract_years,
    format_context,
    format_event,
    fuse_rankings,
    query_terms,
    retrieval_query,
    strip_chunk_header,
)


def chunk(doc, text="Smith v. State (2014-03-27)\nThe court held.", name=None):
    return {
        "doc_id": doc,
        "case_name_short": name or f"Case {doc}",
        "decision_date": "2014-03-27",
        "text": text,
    }


def event(doc, action="affirmed", date="2012-05-04"):
    return {
        "doc_id": doc,
        "case_name_short": f"Case {doc}",
        "decision_date": "2014-03-27",
        "actor": "The court",
        "action": action,
        "target": "the conviction",
        "event_date_iso": date,
        "date_text": None,
        "evidence_quote": "We affirm.",
    }


# ---- rag ---------------------------------------------------------------------------------
def test_extract_years():
    assert extract_years("Who appealed in 1998, and in 2015? Also 1998.") == [1998, 2015]
    assert extract_years("Case 12345 cost $2,000 in 3015") == []


def test_retrieval_query_borrows_previous_question_for_short_follow_ups():
    history = [
        {"role": "user", "content": "Who killed the victim in Weisheit?"},
        {"role": "assistant", "content": "Jeffrey Weisheit [C1]."},
    ]
    assert (
        retrieval_query("And the judge?", history)
        == "Who killed the victim in Weisheit? And the judge?"
    )
    long_q = "What did the court decide about the search of the car in this case?"
    assert retrieval_query(long_q, history) == long_q
    assert retrieval_query("And the judge?", []) == "And the judge?"


def test_build_sources_groups_by_case_in_rank_order():
    chunks = [chunk("a"), chunk("b"), chunk("a"), chunk("a")]
    sources = build_sources(chunks, [event("b"), event("a", "reversed")])
    assert [(s.label, s.doc_id) for s in sources] == [("C1", "a"), ("C2", "b")]
    assert len(sources[0].passages) == PASSAGES_PER_SOURCE
    assert sources[0].passages[0] == "The court held."  # chunk header removed
    assert [e["action"] for e in sources[0].events] == ["reversed"]


def test_build_sources_caps_cases_and_adds_year_events():
    chunks = [chunk(str(i)) for i in range(MAX_SOURCES + 3)]
    assert len(build_sources(chunks, [])) == MAX_SOURCES
    sources = build_sources([chunk("a")], [], [event("z", date="1998-06-01")])
    assert [s.doc_id for s in sources] == ["z", "a"]  # year events come first
    assert sources[0].passages == [] and sources[0].events[0]["event_date_iso"] == "1998-06-01"


def test_year_events_keep_their_slots_but_are_capped():
    chunks = [chunk(f"c{i}") for i in range(MAX_SOURCES)]
    year = [event(f"y{i}", date="2012-01-02") for i in range(YEAR_SOURCES + 2)]
    ids = [s.doc_id for s in build_sources(chunks, [], year)]
    assert ids[:YEAR_SOURCES] == [f"y{i}" for i in range(YEAR_SOURCES)]
    assert len(ids) == MAX_SOURCES and ids[YEAR_SOURCES:] == ["c0", "c1", "c2"]


def test_strip_chunk_header():
    assert strip_chunk_header("Smith v. State (2014-03-27)\nBody") == "Body"
    assert strip_chunk_header("No header line\nBody") == "No header line\nBody"


def test_format_event_and_context():
    line = format_event(event("a"))
    assert line == '- 2012-05-04 | The court | affirmed the conviction — "We affirm."'
    sources = build_sources([chunk("a")], [event("a")])
    ctx = format_context(sources)
    assert ctx.startswith("[C1] Case a (decided 2014-03-27)")
    assert "Extracted events:" in ctx and '"""\nThe court held.\n"""' in ctx
    assert len(format_context(sources, max_chars=20)) == 20


def test_build_messages_keeps_recent_history():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}", "extra": 1}
        for i in range(10)
    ]
    msgs = build_messages("Q?", build_sources([chunk("a")], []), history)
    assert msgs[0]["role"] == "system"
    assert [m["content"] for m in msgs[1:-1]] == ["m6", "m7", "m8", "m9"]
    assert "extra" not in msgs[1]
    assert msgs[-1]["content"].endswith("Question: Q?") and "[C1]" in msgs[-1]["content"]
    assert "(no matching sources found)" in build_messages("Q?", [], [])[-1]["content"]


def test_cited_labels():
    assert cited_labels("Smith appealed [C2]. The court [C1, C3] and [C2; C4].") == [
        "C2",
        "C1",
        "C3",
        "C4",
    ]
    assert cited_labels("No citations, C1 alone is not one.") == []


# ---- display ------------------------------------------------------------------------------
def test_escape_md():
    assert escape_md("$5 *bold* [x]") == r"\$5 \*bold\* \[x\]"


def test_highlight():
    assert (
        highlight("The Court held that the court", "court")
        == "The **Court** held that the **court**"
    )
    assert highlight("a*b", "") == r"a\*b"


def test_tidy_snippet():
    assert tidy_snippet("rt of the\n\n  text here ma") == "…of the text here…"
    assert tidy_snippet("") == ""


def test_cite_links():
    names = {"C1": "Smith v. State", "C2": "Doe v. Roe"}
    assert cite_links("Held [C1]. Both [C1, C2]. Bad [C9].", names) == (
        "Held [C1: Smith v. State]. Both [C1: Smith v. State; C2: Doe v. Roe]. Bad [C9]."
    )


# ---- backend SQL helpers -------------------------------------------------------------------
def test_in_list():
    assert in_list("d", ["x", "y"]) == (":d0, :d1", {"d0": "x", "d1": "y"})
    assert in_list("d", []) == ("NULL", {})


@pytest.mark.parametrize(
    "value, type_name, expected",
    [
        ("3", "INT", 3),
        ("2.5", "DOUBLE", 2.5),
        ("true", "BOOLEAN", True),
        ('["a"]', "ARRAY", ["a"]),
        ("2014-03-27", "DATE", "2014-03-27"),
        (None, "INT", None),
    ],
)
def test_convert(value, type_name, expected):
    assert _convert(value, type_name) == expected


def test_param_types():
    assert _param("n", 5).type == "INT" and _param("n", 5).value == "5"
    assert _param("b", True).value == "true"
    assert _param("s", "x").type is None and _param("s", None).value is None


def test_html_url():
    assert html_url("https://static.case.law/ne3d/1/cases/0131-02.json") == (
        "https://static.case.law/ne3d/1/html/0131-02.html"
    )


def test_author_names():
    raw = [
        "RUSH, Chief Justice.",
        "MÁSSA, J.,",
        "Per Curiam Opinion",
        "Loretta H. Rush, Chief Justice",
        "Massa, Slaughter, Goff, JJ., vote to deny transfer.",
        "--------",
        None,
    ]
    assert author_names(raw) == ["Rush", "Massa", "Per curiam", "Slaughter", "Goff"]
    assert author_names(None) == []


# ---- chat retries --------------------------------------------------------------------------
class _RateLimited(Exception):
    status_code = 429


class _FakeChat:
    def __init__(self, failures: int, status: int = 429):
        self.failures, self.status, self.calls = failures, status, 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            err = _RateLimited("slow down")
            err.status_code = self.status
            raise err
        delta = type("D", (), {"content": "hello"})()
        choice = type("C", (), {"delta": delta})()
        return [type("P", (), {"choices": [choice]})()]


def _backend_with(chat: _FakeChat) -> Backend:
    client = type("O", (), {"chat": type("Ch", (), {"completions": chat})()})()
    serving = type("S", (), {"get_open_ai_client": lambda self: client})()
    b = Backend(client=type("W", (), {"serving_endpoints": serving})())
    b.RETRY_DELAYS_S = (0, 0)
    return b


def test_chat_retries_rate_limits():
    chat = _FakeChat(failures=2)
    assert "".join(_backend_with(chat).chat_stream([])) == "hello" and chat.calls == 3


def test_chat_gives_up_after_retries_and_on_other_errors():
    with pytest.raises(_RateLimited):
        "".join(_backend_with(_FakeChat(failures=5)).chat_stream([]))
    chat = _FakeChat(failures=1, status=400)
    with pytest.raises(_RateLimited):
        "".join(_backend_with(chat).chat_stream([]))
    assert chat.calls == 1


# ---- retrieval helpers -------------------------------------------------------------------
def test_query_terms():
    q = "According to Jefferson County, who started the fire at its courthouse in 2009?"
    assert query_terms(q) == ["jefferson", "county", "started", "fire", "courthouse", "2009"]
    assert query_terms("Who did it?") == []
    assert len(query_terms(" ".join(f"word{i}" for i in range(30)))) == 12


def test_fuse_rankings_rewards_agreement():
    # "t" is 8th by passages but 1st by keywords; "a" is 1st by passages only.
    passages = ["a", "a", "b", "c", "d", "e", "f", "g", "t"]
    keywords = ["t", "x", "b"]
    fused = fuse_rankings(passages, keywords)
    assert fused[:2] == ["b", "t"] and fused.index("t") < fused.index("a") < fused.index("c")
    assert fuse_rankings([], []) == []
