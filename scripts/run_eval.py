"""Score the Ask feature against eval/questions.jsonl, using the same code as the app.

For each question it records:
  - retrieved: the expected case was among the sources given to the model
  - cited: the answer cites that case
  - facts: the answer contains every expected fact (each fact lists accepted spellings)

Writes eval/results.md and exits non-zero if the fact score is below --min-facts.

Usage: uv run python scripts/run_eval.py [--workers 4] [--min-facts 0.8]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import rag  # noqa: E402
from backend import CHAT_MODEL, Backend  # noqa: E402


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split())


def facts_found(answer: str, expect: list[list[str]]) -> list[bool]:
    """For each expected fact, whether any accepted spelling appears in the answer."""
    text = normalize(answer)
    return [any(normalize(option) in text for option in fact) for fact in expect]


def score(item: dict, answer: str, sources: list[rag.Source]) -> dict:
    labels = {s.doc_id: s.label for s in sources}
    found = facts_found(answer, item["expect"])
    return {
        "retrieved": item["doc_id"] in labels,
        "cited": labels.get(item["doc_id"]) in rag.cited_labels(answer),
        "facts": all(found),
        "facts_found": sum(found),
        "facts_total": len(found),
    }


def run_one(backend: Backend, item: dict) -> dict:
    start = time.time()
    try:
        answer, sources = backend.answer(item["question"])
        result = score(item, answer, sources)
    except Exception as e:  # record the failure and keep going
        answer, result = f"ERROR: {e}", {"retrieved": False, "cited": False, "facts": False}
    return {**item, **result, "answer": answer, "seconds": round(time.time() - start, 1)}


def write_report(results: list[dict], path: Path) -> dict:
    n = len(results)
    totals = {k: sum(r[k] for r in results) for k in ("retrieved", "cited", "facts")}
    lines = [
        "# Ask evaluation results",
        "",
        f"Model `{CHAT_MODEL}`, {n} questions from `eval/questions.jsonl`.",
        "",
        "| Metric | Score |",
        "|---|---|",
        f"| Expected case retrieved | {totals['retrieved']}/{n} |",
        f"| Expected case cited | {totals['cited']}/{n} |",
        f"| All expected facts in answer | {totals['facts']}/{n} |",
        f"| Median seconds per answer | {sorted(r['seconds'] for r in results)[n // 2]} |",
        "",
        "| # | Type | Question | Retrieved | Cited | Facts |",
        "|---|---|---|---|---|---|",
    ]
    mark = {True: "✓", False: "✗"}
    for r in results:
        facts = f"{r.get('facts_found', 0)}/{r.get('facts_total', len(r['expect']))}"
        question = r["question"].replace("|", "\\|")
        lines.append(
            f"| {r['id']} | {r['type']} | {question} | {mark[r['retrieved']]} "
            f"| {mark[r['cited']]} | {facts} |"
        )
    misses = [r for r in results if not r["facts"]]
    if misses:
        lines += ["", "## Answers that missed a fact", ""]
        for r in misses:
            lines += [
                f"**{r['id']}. {r['question']}** (expected: {r['case']})",
                "",
                r["answer"],
                "",
            ]
    path.write_text("\n".join(lines) + "\n")
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", type=Path, default=ROOT / "eval" / "questions.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results.md")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--min-facts", type=float, default=0.8)
    args = parser.parse_args()

    items = [json.loads(line) for line in args.questions.read_text().splitlines() if line.strip()]
    backend = Backend()
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda item: run_one(backend, item), items))

    totals = write_report(results, args.out)
    n = len(results)
    for r in results:
        flags = " ".join(f"{k}={'y' if r[k] else 'n'}" for k in ("retrieved", "cited", "facts"))
        print(f"{r['id']} {flags} {r['seconds']:>5}s  {r['question'][:70]}")
    print(
        f"\nretrieved {totals['retrieved']}/{n}  cited {totals['cited']}/{n}  "
        f"facts {totals['facts']}/{n}  -> {args.out.relative_to(ROOT)}"
    )
    return 0 if totals["facts"] >= args.min_facts * n else 1


if __name__ == "__main__":
    sys.exit(main())
