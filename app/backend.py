"""Data access for the app: SQL warehouse queries, Vector Search and the chat model.

On Databricks Apps this runs as the app's service principal, using the resources declared in
databricks.yml (warehouse, model endpoints, tables). Locally it uses your Databricks CLI login.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import rag
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    Disposition,
    ExecuteStatementRequestOnWaitTimeout,
    Format,
    StatementParameterListItem,
    StatementState,
)

CATALOG = os.getenv("CATALOG", "legal_demo")
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "bcb6defe8c0fdebf")
CHAT_MODEL = os.getenv("CHAT_MODEL", "databricks-qwen3-next-80b-a3b-instruct")
VS_INDEX = os.getenv("VS_INDEX", f"{CATALOG}.silver.chunks_index")

DOCS = f"{CATALOG}.silver.documents"
ENTITIES = f"{CATALOG}.gold.entities"
EVENTS = f"{CATALOG}.gold.events"

_INT_TYPES = {"BYTE", "SHORT", "INT", "LONG"}
_FLOAT_TYPES = {"FLOAT", "DOUBLE", "DECIMAL"}
_JSON_TYPES = {"ARRAY", "MAP", "STRUCT"}
_TERMINAL = {StatementState.SUCCEEDED, StatementState.FAILED, StatementState.CANCELED}


def _param(name: str, value) -> StatementParameterListItem:
    if isinstance(value, bool):
        return StatementParameterListItem(name=name, value=str(value).lower(), type="BOOLEAN")
    if isinstance(value, int):
        return StatementParameterListItem(name=name, value=str(value), type="INT")
    return StatementParameterListItem(name=name, value=None if value is None else str(value))


def _convert(value: str | None, type_name: str):
    if value is None:
        return None
    if type_name in _INT_TYPES:
        return int(value)
    if type_name in _FLOAT_TYPES:
        return float(value)
    if type_name == "BOOLEAN":
        return value.lower() == "true"
    if type_name in _JSON_TYPES:
        return json.loads(value)
    return value  # STRING, and DATE/TIMESTAMP as ISO strings


def rows_to_frame(names: list[str], types: list[str], rows: list[list]) -> pd.DataFrame:
    """Typed Python values in an object DataFrame. Object dtype keeps missing values as None
    and numbers as ints: pandas 3 would otherwise turn a missing string into NaN (a float),
    which breaks code that joins or tests text."""
    data = [[_convert(v, t) for v, t in zip(row, types, strict=True)] for row in rows]
    return pd.DataFrame(data, columns=names, dtype=object)


def in_list(prefix: str, values: list) -> tuple[str, dict]:
    """SQL `IN (...)` placeholders and their parameters, e.g. (":d0, :d1", {"d0": .., "d1": ..})."""
    params = {f"{prefix}{i}": v for i, v in enumerate(values)}
    return ", ".join(f":{k}" for k in params) or "NULL", params


class Backend:
    def __init__(self, client: WorkspaceClient | None = None):
        self.w = client or WorkspaceClient()

    # ---- SQL ---------------------------------------------------------------------------
    def sql(self, statement: str, params: dict | None = None, timeout_s: int = 120) -> pd.DataFrame:
        """Run a parameterized statement on the warehouse and return the rows as a DataFrame."""
        api = self.w.statement_execution
        resp = api.execute_statement(
            statement=statement,
            warehouse_id=WAREHOUSE_ID,
            parameters=[_param(k, v) for k, v in (params or {}).items()],
            disposition=Disposition.INLINE,
            format=Format.JSON_ARRAY,
            wait_timeout="30s",
            on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
        )
        start = time.time()
        while resp.status.state not in _TERMINAL:  # warehouse starting up, or a slow query
            if time.time() - start > timeout_s:
                api.cancel_execution(resp.statement_id)
                raise TimeoutError(f"query took longer than {timeout_s}s")
            time.sleep(1)
            resp = api.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            error = resp.status.error.message if resp.status.error else resp.status.state
            raise RuntimeError(f"query failed: {error}")

        columns = resp.manifest.schema.columns or []
        rows = list(resp.result.data_array or []) if resp.result else []
        chunk = resp.result.next_chunk_index if resp.result else None
        while chunk is not None:
            part = api.get_statement_result_chunk_n(resp.statement_id, chunk)
            rows.extend(part.data_array or [])
            chunk = part.next_chunk_index
        types = [c.type_name.value if c.type_name else "STRING" for c in columns]
        return rows_to_frame([c.name for c in columns], types, rows)

    # ---- Browse ------------------------------------------------------------------------
    def documents(self) -> pd.DataFrame:
        """Metadata for every case (no full text), with counts of extracted people and events."""
        return self.sql(f"""
            SELECT d.doc_id, d.case_name_short, d.case_name, d.decision_date, d.citation,
                   d.docket_number, d.opinion_types, d.opinion_authors, d.char_count,
                   coalesce(e.n, 0) AS people, coalesce(v.n, 0) AS events
            FROM {DOCS} d
            LEFT JOIN (SELECT doc_id, count(*) n FROM {ENTITIES} GROUP BY doc_id) e USING (doc_id)
            LEFT JOIN (SELECT doc_id, count(*) n FROM {EVENTS} GROUP BY doc_id) v USING (doc_id)
            ORDER BY d.decision_date DESC, d.case_name_short""")

    def document(self, doc_id: str) -> dict | None:
        df = self.sql(
            f"SELECT * EXCEPT (source_file) FROM {DOCS} WHERE doc_id = :id", {"id": doc_id}
        )
        return df.iloc[0].to_dict() if len(df) else None

    def entities(self, doc_id: str) -> pd.DataFrame:
        return self.sql(
            f"""SELECT name, entity_type, role, description, mention_count FROM {ENTITIES}
                WHERE doc_id = :id ORDER BY mention_count DESC, name""",
            {"id": doc_id},
        )

    def events(self, doc_ids: list[str], per_doc: int = 200) -> pd.DataFrame:
        """Extracted events for some cases, in date order (undated events last)."""
        placeholders, params = in_list("d", doc_ids)
        return self.sql(
            f"""SELECT doc_id, case_name_short, decision_date, actor, action, target,
                       event_date_iso, date_text, description, evidence_quote, quote_verified
                FROM {EVENTS} WHERE doc_id IN ({placeholders})
                QUALIFY row_number() OVER (
                  PARTITION BY doc_id ORDER BY quote_verified DESC, event_id) <= :per_doc
                ORDER BY doc_id, event_date_iso IS NULL, event_date_iso, event_id""",
            {**params, "per_doc": per_doc},
        )

    def events_in_years(self, years: list[int], limit: int = 30) -> pd.DataFrame:
        """Events whose own date falls in one of these years, verified quotes first."""
        placeholders, params = in_list("y", [str(y) for y in years])
        return self.sql(
            f"""SELECT doc_id, case_name_short, decision_date, actor, action, target,
                       event_date_iso, date_text, description, evidence_quote, quote_verified
                FROM {EVENTS}
                WHERE left(event_date_iso, 4) IN ({placeholders})
                ORDER BY quote_verified DESC, event_date_iso, event_id LIMIT :limit""",
            {**params, "limit": limit},
        )

    # ---- Search ------------------------------------------------------------------------
    def keyword_search(self, query: str, limit: int = 50) -> pd.DataFrame:
        """Cases whose text contains the exact words, with a snippet around the first match."""
        return self.sql(
            f"""SELECT doc_id, case_name_short, decision_date, citation,
                       substr(full_text, greatest(1, pos - 200), 500) AS snippet,
                       (length(full_text) - length(replace(lower(full_text), lower(:q), '')))
                         DIV length(:q) AS matches
                FROM (SELECT *, instr(lower(full_text), lower(:q)) AS pos FROM {DOCS})
                WHERE pos > 0
                ORDER BY matches DESC, decision_date DESC LIMIT :limit""",
            {"q": query, "limit": limit},
        )

    def people_search(self, name: str, limit: int = 100) -> pd.DataFrame:
        return self.sql(
            f"""SELECT name, role, entity_type, doc_id, case_name_short, decision_date, description
                FROM {ENTITIES} WHERE instr(lower(name), lower(:q)) > 0
                ORDER BY mention_count DESC, decision_date DESC LIMIT :limit""",
            {"q": name, "limit": limit},
        )

    def keyword_case_ranking(self, terms: list[str], limit: int = 20) -> list[str]:
        """Cases ranked by which question words their full text contains, rare words counting
        more (IDF). Complements chunk search, where one case with many similar passages can
        crowd out a case that matches the question's distinctive words."""
        if not terms:
            return []
        placeholders, params = in_list("t", terms)
        df = self.sql(
            f"""WITH terms AS (SELECT explode(array({placeholders})) AS term),
                hits AS (SELECT d.doc_id, t.term FROM {DOCS} d JOIN terms t
                         ON instr(lower(d.full_text), t.term) > 0),
                freq AS (SELECT term, count(*) AS n FROM hits GROUP BY term)
                SELECT h.doc_id, sum(ln((SELECT count(*) FROM {DOCS}) / f.n)) AS score
                FROM hits h JOIN freq f USING (term)
                GROUP BY h.doc_id ORDER BY score DESC, h.doc_id LIMIT :limit""",
            {**params, "limit": limit},
        )
        return list(df.doc_id)

    def semantic_search(self, query: str, k: int = 20, doc_id: str | None = None) -> list[dict]:
        """Hybrid (meaning + keyword) search over opinion chunks. Returns chunks with a score."""
        resp = self.w.vector_search_indexes.query_index(
            VS_INDEX,
            columns=[
                "chunk_id",
                "doc_id",
                "chunk_index",
                "case_name_short",
                "decision_date",
                "text",
            ],
            query_text=query,
            query_type="HYBRID",
            num_results=k,
            filters_json=json.dumps({"doc_id": doc_id}) if doc_id else None,
        )
        names = [c.name for c in resp.manifest.columns]
        return [dict(zip(names, row, strict=True)) for row in resp.result.data_array or []]

    # ---- Chat --------------------------------------------------------------------------
    # Free Edition rate-limits pay-per-token models (HTTP 429), so busy moments need retries.
    RETRY_STATUS = {429, 500, 502, 503, 504}
    RETRY_DELAYS_S = (1, 2, 4, 8)

    def chat_stream(self, messages: list[dict], max_tokens: int = 1500) -> Iterator[str]:
        """Stream the chat model's reply, piece by piece. Retries rate limits and server
        errors that happen before the reply starts."""
        for delay in (*self.RETRY_DELAYS_S, None):
            # A fresh OpenAI client per call picks up a current OAuth token.
            client = self.w.serving_endpoints.get_open_ai_client()
            try:
                stream = client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.1,
                    stream=True,
                )
                break
            except Exception as e:
                if delay is None or getattr(e, "status_code", None) not in self.RETRY_STATUS:
                    raise
                time.sleep(delay)
        for part in stream:
            if part.choices and part.choices[0].delta and part.choices[0].delta.content:
                yield part.choices[0].delta.content

    # ---- Question answering ------------------------------------------------------------
    def gather_sources(
        self, question: str, scope: str | None = None, history: list[dict] | None = None
    ) -> list:
        """Find the sources for a question: search hits plus extracted events (see rag.py)."""
        history = history or []
        query = rag.retrieval_query(question, history)
        if scope:
            chunks = self.semantic_search(query, k=12, doc_id=scope)
            doc_ids = [scope]
        else:
            # Passage search and whole-case keyword ranking, run in parallel, then fused.
            with ThreadPoolExecutor(2) as pool:
                hits = pool.submit(self.semantic_search, query, 30)
                keyword = pool.submit(self.keyword_case_ranking, rag.query_terms(query))
                hits, keyword = hits.result(), keyword.result()
            by_passage = [h["doc_id"] for h in hits]
            doc_ids = rag.fuse_rankings(by_passage, keyword)[: rag.MAX_SOURCES]
            missing = [d for d in doc_ids if d not in set(by_passage)]
            if missing:  # cases found only by keywords: get their best passages
                with ThreadPoolExecutor(len(missing)) as pool:
                    for part in pool.map(lambda d: self.semantic_search(query, 2, d), missing):
                        hits += part
            rank = {d: i for i, d in enumerate(doc_ids)}
            chunks = sorted(
                (h for h in hits if h["doc_id"] in rank), key=lambda h: rank[h["doc_id"]]
            )
        events = self.events(doc_ids, rag.EVENTS_PER_SOURCE)
        years = [] if scope else rag.extract_years(question)
        year_events = self.events_in_years(years) if years else pd.DataFrame()
        return rag.build_sources(chunks, events.to_dict("records"), year_events.to_dict("records"))

    def answer(self, question: str, scope: str | None = None) -> tuple[str, list]:
        """Answer a question in one go (no streaming). Returns (answer, sources)."""
        sources = self.gather_sources(question, scope)
        text = "".join(self.chat_stream(rag.build_messages(question, sources, [])))
        return text, sources
