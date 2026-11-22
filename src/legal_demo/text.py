"""Turn CAP case JSON into clean document records and text chunks."""

from __future__ import annotations

import re
from datetime import date

from legal_demo.cap import case_url

# Search chunks: about 750 tokens each, with overlap so a sentence cut at a boundary still
# appears whole in one chunk.
CHUNK_CHARS = 3000
CHUNK_OVERLAP = 400

# LLM extraction segments: about 6k tokens each, so most opinions need one call.
SEGMENT_CHARS = 24000
SEGMENT_OVERLAP = 1000


def parse_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD. Partial dates (YYYY-MM, YYYY) and bad values return None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def build_full_text(case: dict) -> str:
    """Head matter followed by each opinion, with a header naming its type and author."""
    body = case.get("casebody") or {}
    parts = []
    head = (body.get("head_matter") or "").strip()
    if head:
        parts.append(head)
    for op in body.get("opinions") or []:
        text = (op.get("text") or "").strip()
        if not text:
            continue
        header = f"--- {(op.get('type') or 'opinion').upper()} OPINION"
        if op.get("author"):
            header += f" ({op['author'].strip()})"
        parts.append(f"{header} ---\n{text}")
    return "\n\n".join(parts)


def case_to_document(case: dict, reporter: str, volume: str, source_file: str) -> dict:
    """Flatten a CAP case into a row for silver.documents."""
    body = case.get("casebody") or {}
    opinions = body.get("opinions") or []
    citations = case.get("citations") or []
    official = next((c["cite"] for c in citations if c.get("type") == "official"), None)
    full_text = build_full_text(case)
    return {
        "doc_id": str(case["id"]),
        "case_name": case.get("name"),
        "case_name_short": case.get("name_abbreviation"),
        "decision_date": parse_date(case.get("decision_date")),
        "docket_number": case.get("docket_number"),
        "citation": official or (citations[0]["cite"] if citations else None),
        "court": (case.get("court") or {}).get("name"),
        "reporter": reporter,
        "volume": str(volume),
        "parties": [p.strip() for p in body.get("parties") or []],
        "judges": [j.strip() for j in body.get("judges") or []],
        "attorneys": [a.strip() for a in body.get("attorneys") or []],
        "opinion_types": [o.get("type") for o in opinions],
        "opinion_authors": [o.get("author") for o in opinions if o.get("author")],
        "head_matter": body.get("head_matter"),
        "full_text": full_text,
        "char_count": len(full_text),
        "source_url": case_url(reporter, volume, case["file_name"]),
        "source_file": source_file,
    }


def _split_long(paragraph: str, limit: int) -> list[str]:
    """Split a paragraph longer than `limit` on word boundaries."""
    pieces, current = [], ""
    for word in paragraph.split():
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    # A single "word" longer than the limit (rare: URLs, tables) gets hard-split.
    return [p[i : i + limit] for p in pieces for i in range(0, len(p), limit)]


def chunk_text(text: str, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Pack paragraphs into chunks of at most `max_chars`, with ~`overlap` chars repeated."""
    if overlap >= max_chars // 2:
        raise ValueError("overlap must be less than half of max_chars")
    piece_limit = max_chars - overlap - 1
    pieces: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if para:
            pieces.extend(_split_long(para, piece_limit) if len(para) > piece_limit else [para])

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > max_chars:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1 :]  # start the overlap on a word boundary
            current = f"{tail}\n{piece}" if tail else piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def document_to_chunks(doc: dict) -> list[dict]:
    """Rows for silver.chunks. Each chunk starts with the case name and date for retrieval."""
    header = f"{doc['case_name_short']} ({doc['decision_date'] or 'undated'})"
    return [
        {
            "chunk_id": f"{doc['doc_id']}-{i:04d}",
            "doc_id": doc["doc_id"],
            "chunk_index": i,
            "case_name_short": doc["case_name_short"],
            "decision_date": doc["decision_date"],
            "text": f"{header}\n{chunk}",
        }
        for i, chunk in enumerate(chunk_text(doc["full_text"]))
    ]


def normalize_for_match(text: str) -> str:
    """Lowercase and collapse whitespace and quote styles, for checking that quotes are verbatim."""
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"').replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()
