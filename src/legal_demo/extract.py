"""LLM extraction of people, organizations and events (who did what, when) from opinions."""

from __future__ import annotations

import json
import re
import time
from datetime import date

from legal_demo.text import normalize_for_match

# Bump when the prompt or output shape changes; the pipeline re-extracts anything older.
PROMPT_VERSION = "v2"
MAX_OUTPUT_TOKENS = 4000

ENTITY_TYPES = {"person", "organization", "court", "government"}

SYSTEM_PROMPT = """You extract structured facts from US court opinions for a legal research database.
Return ONLY a JSON object, with no other text, in exactly this shape:
{"entities": [{"name": str, "type": "person"|"organization"|"court"|"government", "role": str, "description": str}],
 "events": [{"actor": str, "action": str, "target": str|null, "date": str|null, "date_text": str|null, "description": str, "quote": str}]}

Rules:
- entities: people and organizations NAMED in the text: parties, justices and judges, attorneys,
  witnesses, victims, trial courts, agencies. "role" is their role in this case, for example
  "appellant", "appellee", "defendant", "victim", "witness", "justice (author)",
  "justice (dissenting)", "attorney for appellant", "trial court". Use the fullest name given.
  Skip people who are never named (for example "the officer"). List each entity once.
- description: one short sentence (under 20 words).
- events: concrete actions: the conduct that gave rise to the case, arrests, charges, filings,
  trial events, verdicts, sentences, appeals, and this court's decision (affirmed, reversed,
  remanded, vacated). At most 20 events, the most legally significant, in chronological order.
- actor and target: use the entity names where possible. "action" is a short verb phrase.
- date: ISO 8601 (YYYY-MM-DD, or YYYY-MM or YYYY if that is all the text says) ONLY when the
  text states it. Never guess or infer a date. Otherwise null.
- date_text: the date exactly as written in the text, or null.
- quote: a short excerpt (under 30 words) copied EXACTLY from the text that supports the event.
- If there is nothing to extract, return {"entities": [], "events": []}."""


def build_messages(case_name: str, decision_date, segment: str, index: int, total: int) -> list:
    user = (
        f"Case: {case_name} (decided {decision_date or 'unknown'})\n"
        f"Segment {index + 1} of {total}\n\nTEXT:\n{segment}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def message_text(content) -> str:
    """Some models return a list of content parts instead of a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if p.get("type") == "text")
    return str(content)


def call_chat(client, model: str, messages: list[dict], *, retries: int = 6) -> tuple[str, float]:
    """Query a Foundation Model API chat endpoint, with backoff on rate limits and errors.

    Returns (response_text, seconds). `client` is a databricks.sdk.WorkspaceClient.
    """
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

    chat = [ChatMessage(role=ChatMessageRole(m["role"]), content=m["content"]) for m in messages]
    delay = 5.0
    for attempt in range(retries):
        start = time.time()
        try:
            resp = client.serving_endpoints.query(
                name=model, messages=chat, max_tokens=MAX_OUTPUT_TOKENS, temperature=0
            )
            return message_text(resp.choices[0].message.content), time.time() - start
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError("unreachable")


def _close_open_brackets(s: str) -> str | None:
    """Append the brackets needed to close `s`, or None if it ends inside a string."""
    stack, in_str, escaped = [], False, False
    for ch in s:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    if in_str:
        return None
    return s + "".join("}" if c == "{" else "]" for c in reversed(stack))


def _repair_truncated(body: str, error_pos: int) -> dict | None:
    """Keep everything up to the last complete object before `error_pos`, then close it.

    Long replies can hit the output token limit and stop mid-object. This recovers the
    entities and events that were finished.
    """
    cut = body.rfind("}", 0, error_pos)
    for _ in range(200):
        if cut <= 0:
            return None
        candidate = _close_open_brackets(body[: cut + 1])
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        cut = body.rfind("}", 0, cut)
    return None


def _json_object(text: str) -> tuple[dict, bool]:
    """Pull the JSON object out of a model reply that may have code fences or extra text.

    Returns (data, repaired). `repaired` is True when the reply was cut off and only its
    complete part was kept.
    """
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in response")
    body = text[start:]
    end = body.rfind("}")
    try:
        return json.loads(body[: end + 1]), False
    except json.JSONDecodeError as e:
        repaired = _repair_truncated(body, e.pos)
        if repaired is None:
            raise ValueError(f"unparseable JSON: {e}") from e
        return repaired, True


def _clean(value, limit: int = 500) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value[:limit] or None


def normalize_date(value) -> tuple[date | None, str | None]:
    """Return (full date or None, ISO string as given if valid: YYYY-MM-DD, YYYY-MM or YYYY)."""
    value = _clean(value, 20)
    if not value:
        return None, None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value), value
        except ValueError:
            return None, None
    if re.fullmatch(r"\d{4}(-\d{2})?", value):
        return None, value
    return None, None


_MONTHS = (
    "jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june "
    "july august september october november december"
).split()


def drop_padded_day(
    event_date: date | None, iso: str | None, date_text: str | None
) -> tuple[date | None, str | None]:
    """Undo a model padding a partial date: "1999" → 1999-01-01, "December 2010" → 2010-12-01.

    If the date is on the 1st but the quoted date text names no day, keep only the month
    (when the text names one) or the year.
    """
    if event_date is None or event_date.day != 1 or not date_text:
        return event_date, iso
    text = date_text.lower()
    if re.search(r"(?<!\d)0?1(st)?(?!\d)|\bfirst\b", text):
        return event_date, iso
    if any(re.search(rf"\b{m}\b", text) for m in _MONTHS):
        return None, event_date.isoformat()[:7]
    return None, str(event_date.year)


def parse_extraction(text: str) -> dict:
    """Parse and clean a model reply into {"entities": [...], "events": [...], "repaired": bool}."""
    data, repaired = _json_object(text)
    if not isinstance(data, dict):
        raise ValueError("response JSON is not an object")
    entities = []
    for e in data.get("entities") or []:
        if not isinstance(e, dict) or not _clean(e.get("name")):
            continue
        etype = (_clean(e.get("type"), 40) or "").lower()
        entities.append(
            {
                "name": _clean(e.get("name"), 200),
                "entity_type": etype if etype in ENTITY_TYPES else "other",
                "role": _clean(e.get("role"), 100),
                "description": _clean(e.get("description")),
            }
        )
    events = []
    for ev in data.get("events") or []:
        if not isinstance(ev, dict) or not _clean(ev.get("action")):
            continue
        date_text = _clean(ev.get("date_text"), 100)
        event_date, event_date_iso = drop_padded_day(*normalize_date(ev.get("date")), date_text)
        events.append(
            {
                "actor": _clean(ev.get("actor"), 200),
                "action": _clean(ev.get("action"), 200),
                "target": _clean(ev.get("target"), 200),
                "event_date": event_date,
                "event_date_iso": event_date_iso,
                "date_text": date_text,
                "description": _clean(ev.get("description")),
                "evidence_quote": _clean(ev.get("quote"), 400),
            }
        )
    return {"entities": entities, "events": events, "repaired": repaired}


def quote_is_verbatim(quote: str | None, normalized_source: str) -> bool:
    """True if the quote (ignoring case, whitespace, quote styles and '...') is in the source."""
    if not quote:
        return False
    parts = [normalize_for_match(p).strip(" .\"'") for p in re.split(r"\.\.\.|…", quote)]
    parts = [p for p in parts if len(p) >= 8]
    return bool(parts) and all(p in normalized_source for p in parts)


def merge_entities(per_segment: list[list[dict]]) -> list[dict]:
    """Combine entities found in several segments of one document, keyed by (name, role)."""
    merged: dict[tuple, dict] = {}
    for entities in per_segment:
        for e in entities:
            key = (e["name"].lower(), (e["role"] or "").lower())
            if key in merged:
                merged[key]["mention_count"] += 1
                merged[key]["description"] = merged[key]["description"] or e["description"]
            else:
                merged[key] = {**e, "mention_count": 1}
    return list(merged.values())
