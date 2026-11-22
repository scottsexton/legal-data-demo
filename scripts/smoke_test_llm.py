"""Smoke-test Databricks Foundation Model API endpoints from your laptop.

Usage:
    uv run python scripts/smoke_test_llm.py                 # default candidates
    uv run python scripts/smoke_test_llm.py databricks-gpt-oss-120b

Uses the DEFAULT profile in ~/.databrickscfg (created by `databricks auth login`).
"""

from __future__ import annotations

import json
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

DEFAULT_CHAT_MODELS = [
    "databricks-meta-llama-3-3-70b-instruct",
    "databricks-gpt-oss-120b",
    "databricks-qwen3-next-80b-a3b-instruct",
]
EMBEDDING_MODEL = "databricks-gte-large-en"

SAMPLE = (
    "On March 3, 2017, the Marion Superior Court convicted John Doe of burglary. "
    "Doe appealed, and on June 20, 2018, the Indiana Supreme Court, in an opinion by "
    "Justice Rush, reversed the conviction and remanded for a new trial."
)
PROMPT = (
    "Extract every event from the text as a JSON array of objects with keys "
    '"actor", "action", "target", "date" (ISO 8601). Return only JSON.\n\n' + SAMPLE
)


def message_text(content) -> str:
    """Some models (e.g. gpt-oss) return a list of content parts instead of a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if p.get("type") == "text")
    return str(content)


def test_chat(w: WorkspaceClient, model: str) -> None:
    start = time.time()
    resp = w.serving_endpoints.query(
        name=model,
        messages=[ChatMessage(role=ChatMessageRole.USER, content=PROMPT)],
        max_tokens=600,
        temperature=0,
    )
    text = message_text(resp.choices[0].message.content).strip()
    cleaned = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        events = json.loads(cleaned)
        status = f"valid JSON, {len(events)} events"
    except json.JSONDecodeError:
        status = "NOT valid JSON"
    print(f"\n=== {model}  ({time.time() - start:.1f}s, {status})\n{text}")


def test_embedding(w: WorkspaceClient) -> None:
    resp = w.serving_endpoints.query(name=EMBEDDING_MODEL, input=[SAMPLE])
    print(f"\n=== {EMBEDDING_MODEL}: vector length {len(resp.data[0].embedding)}")


def main() -> None:
    w = WorkspaceClient()
    for model in sys.argv[1:] or DEFAULT_CHAT_MODELS:
        try:
            test_chat(w, model)
        except Exception as e:  # keep going so one bad endpoint doesn't hide the rest
            print(f"\n=== {model}: ERROR {e}")
    test_embedding(w)


if __name__ == "__main__":
    main()
