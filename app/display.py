"""Small text helpers for showing opinion text safely in Streamlit markdown."""

from __future__ import annotations

import re
import unicodedata

# Indiana Supreme Court justices who wrote opinions in 2013–2019.
JUSTICES = ["David", "Dickson", "Goff", "Massa", "Rucker", "Rush", "Slaughter"]

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#+|$~])")


def escape_md(text: str) -> str:
    """Escape characters Streamlit markdown would treat as formatting (or LaTeX, for `$`)."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def highlight(text: str, query: str) -> str:
    """Escape `text` for markdown and bold each case-insensitive match of `query`."""
    if not query.strip():
        return escape_md(text)
    pieces = re.split(f"({re.escape(query.strip())})", text or "", flags=re.IGNORECASE)
    return "".join(
        f"**{escape_md(p)}**" if i % 2 else escape_md(p) for i, p in enumerate(pieces) if p
    )


def tidy_snippet(text: str) -> str:
    """Collapse whitespace and trim a snippet to whole words, with ellipses."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    words = text.split(" ")
    if len(words) > 2:
        words = words[1:-1]  # the first and last words are usually cut off
    return f"…{' '.join(words)}…"


def cite_links(answer: str, labels: dict[str, str]) -> str:
    """Turn [C1] citations into [C1: Case Name] so readers see which case is meant."""

    def repl(m: re.Match) -> str:
        inner = [x.strip() for x in re.split(r"[,;]", m.group(1))]
        named = [f"{x}: {labels[x]}" if x in labels else x for x in inner]
        return "[" + "; ".join(named) + "]"

    return re.sub(r"\[(C\d+(?:\s*[,;]\s*C\d+)*)\]", repl, answer)


def html_url(source_url: str) -> str:
    """CAP JSON file URL → the readable HTML page for the same case."""
    return source_url.replace("/cases/", "/html/").removesuffix(".json") + ".html"


def author_names(raw_authors: list[str] | None) -> list[str]:
    """Clean opinion-author strings ("RUSH, Chief Justice.", "MÁSSA, J.,", "Per Curiam.") into
    justice surnames or "Per curiam", in order, without repeats. The raw text is noisy OCR."""
    names = []
    for raw in raw_authors or []:
        plain = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode().upper()
        if "PER CURIAM" in plain:
            names.append("Per curiam")
            continue
        found = [
            (m.start(), j) for j in JUSTICES for m in [re.search(rf"\b{j.upper()}\b", plain)] if m
        ]
        names += [j for _, j in sorted(found)]
    return list(dict.fromkeys(names))
