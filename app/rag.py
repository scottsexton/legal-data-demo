"""Question answering over the opinions: gather sources, build the prompt, read citations.

Pure functions (no Databricks calls), so they can be unit tested.

Each answer draws on up to MAX_SOURCES cases. A case's source has passages from the opinion
(found by hybrid Vector Search) and the people/dates/actions extracted into gold.events. A
question that names a year also gets up to YEAR_SOURCES cases with events dated that year,
since the cases were decided in 2013–2019 but describe events from much earlier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_SOURCES = 6
YEAR_SOURCES = 3  # slots kept for cases with events in a year the question names
PASSAGES_PER_SOURCE = 2
EVENTS_PER_SOURCE = 12
MAX_CONTEXT_CHARS = 40_000
HISTORY_MESSAGES = 4

SYSTEM_PROMPT = """You are a research assistant for a demo built on Indiana Supreme Court \
opinions (decided 2013–2019, from the Caselaw Access Project). Answer the question using only \
the sources below. Each source is one case, labelled [C1], [C2] and so on, with events \
extracted from it and passages quoted from it.

Rules:
- Cite the source label after each fact, like [C2]. Cite only labels that appear below.
- Focus on the people (parties, judges, attorneys, witnesses), the dates and the actions.
- Give dates exactly as precise as the source: don't add a day or month that isn't stated.
- Prefer the passages over the extracted events when they disagree; passages are the opinion.
- If the sources don't answer the question, say so plainly and suggest a better question.
- Be concise: a short paragraph or a few bullets. Don't give legal advice."""


@dataclass
class Source:
    label: str
    doc_id: str
    case_name: str
    decision_date: str | None
    passages: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


def extract_years(text: str) -> list[int]:
    """Four-digit years (1800–2099) mentioned in the text, in order, without repeats."""
    years = [int(y) for y in re.findall(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", text)]
    return list(dict.fromkeys(years))


# Words that say nothing about which case is meant.
STOPWORDS = set(
    """about after again against also among an and any are around as at be been before being
    between both but by can case cases could court courts did do does doing done during each
    for from had has have he her here him his how if in into is it its legal many may more
    most much not of on one only opinion opinions or other our out over said same she should
    so some such than that the their them then there these they this those through to under
    until up upon was we were what when where which while who whom whose why will with would
    you your according tell give list show happened""".split()
)
FUSION_K = 60  # standard reciprocal-rank-fusion constant


def query_terms(question: str, max_terms: int = 12) -> list[str]:
    """Lowercased content words (4+ letters, or any number) for keyword ranking of cases."""
    words = re.findall(r"[a-z0-9][a-z0-9'\-]*", question.lower())
    terms = [w.strip("'-") for w in words]
    terms = [t for t in terms if t not in STOPWORDS and (len(t) >= 4 or t.isdigit())]
    return list(dict.fromkeys(terms))[:max_terms]


def fuse_rankings(*rankings: list[str], k: int = FUSION_K) -> list[str]:
    """Reciprocal rank fusion: merge ranked lists of ids; ids high in several lists win."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(dict.fromkeys(ranking), start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: -scores[item])


def retrieval_query(question: str, history: list[dict]) -> str:
    """The text to search with. Short follow-ups ("and who was the judge?") borrow context
    from the previous question."""
    previous = [m["content"] for m in history if m["role"] == "user"]
    if previous and len(question.split()) < 8:
        return f"{previous[-1]} {question}"
    return question


def build_sources(chunks: list[dict], events: list[dict], year_events: list[dict] = ()) -> list:
    """Group search hits and events into labelled sources.

    Cases with events in a year the question names come first (up to YEAR_SOURCES), so the
    search hits can't crowd them out; then search hits in rank order."""
    sources: dict[str, Source] = {}

    def source_for(row: dict, limit: int = MAX_SOURCES) -> Source | None:
        doc_id = row["doc_id"]
        if doc_id not in sources:
            if len(sources) >= limit:
                return None
            sources[doc_id] = Source(
                label=f"C{len(sources) + 1}",
                doc_id=doc_id,
                case_name=row.get("case_name_short") or doc_id,
                decision_date=row.get("decision_date"),
            )
        return sources[doc_id]

    def add_event(src: Source | None, event: dict) -> None:
        if src and len(src.events) < EVENTS_PER_SOURCE and event not in src.events:
            src.events.append(event)

    for event in year_events:
        add_event(source_for(event, YEAR_SOURCES), event)
    for chunk in chunks:
        src = source_for(chunk)
        if src and len(src.passages) < PASSAGES_PER_SOURCE:
            src.passages.append(strip_chunk_header(chunk["text"]))
    for event in events:
        add_event(source_for(event), event)
    return list(sources.values())


def strip_chunk_header(text: str) -> str:
    """Chunks start with a "Case Name (date)" line for embedding; the source header has it."""
    first, _, rest = text.partition("\n")
    return rest if rest and first.endswith(")") else text


def format_event(e: dict) -> str:
    when = e.get("event_date_iso") or e.get("date_text") or "undated"
    who = e.get("actor") or "?"
    what = " ".join(x for x in (e.get("action"), e.get("target")) if x)
    quote = f' — "{e["evidence_quote"]}"' if e.get("evidence_quote") else ""
    return f"- {when} | {who} | {what}{quote}"


def format_context(sources: list[Source], max_chars: int = MAX_CONTEXT_CHARS) -> str:
    parts, used = [], 0
    for s in sources:
        lines = [f"[{s.label}] {s.case_name} (decided {s.decision_date or 'unknown'})"]
        if s.events:
            lines.append("Extracted events:")
            lines += [format_event(e) for e in s.events]
        for p in s.passages:
            lines.append(f'Passage:\n"""\n{p.strip()}\n"""')
        block = "\n".join(lines)
        if used + len(block) > max_chars:
            block = block[: max(0, max_chars - used)]
        parts.append(block)
        used += len(block)
        if used >= max_chars:
            break
    return "\n\n".join(parts)


def build_messages(question: str, sources: list[Source], history: list[dict]) -> list[dict]:
    """System prompt, recent conversation, then the sources and the new question."""
    recent = [{"role": m["role"], "content": m["content"]} for m in history[-HISTORY_MESSAGES:]]
    context = format_context(sources) if sources else "(no matching sources found)"
    user = f"Sources:\n\n{context}\n\nQuestion: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *recent,
        {"role": "user", "content": user},
    ]


def cited_labels(answer: str) -> list[str]:
    """Source labels cited in an answer, in order of first use: "[C2], [C1][C3]" → C2, C1, C3."""
    labels = re.findall(r"\bC\d+\b", " ".join(re.findall(r"\[(C\d+(?:\s*[,;]\s*C\d+)*)\]", answer)))
    return list(dict.fromkeys(labels))
