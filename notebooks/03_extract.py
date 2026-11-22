# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Extract people, dates and actions with an LLM
# MAGIC 1. Split each opinion into ~24k-character segments and send each to the chat model.
# MAGIC 2. Save every raw reply to `bronze.extractions_raw`. Re-runs skip segments already done with
# MAGIC    the same model and prompt version, so an interrupted run resumes.
# MAGIC 3. Parse the replies into `gold.entities` and `gold.events`. Each event's quote is checked
# MAGIC    against the opinion text (`quote_verified`).

# COMMAND ----------

dbutils.widgets.text("catalog", "legal_demo")
dbutils.widgets.text("chat_model", "databricks-qwen3-next-80b-a3b-instruct")
dbutils.widgets.text("max_docs", "0", "Max documents (0 = all)")
dbutils.widgets.text("workers", "6", "Parallel LLM calls")
dbutils.widgets.text("code_path", "/Volumes/legal_demo/raw/code/dev")
catalog = dbutils.widgets.get("catalog")
chat_model = dbutils.widgets.get("chat_model")
max_docs = int(dbutils.widgets.get("max_docs") or 0)
workers = int(dbutils.widgets.get("workers") or 6)

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

# Shared code lives in a Volume (see 02_transform.py for why).
sys.path.insert(0, dbutils.widgets.get("code_path"))

from databricks.sdk import WorkspaceClient
from pyspark.sql import types as T

from legal_demo.extract import (
    PROMPT_VERSION,
    build_messages,
    call_chat,
    merge_entities,
    parse_extraction,
    quote_is_verbatim,
)
from legal_demo.text import SEGMENT_CHARS, SEGMENT_OVERLAP, chunk_text, normalize_for_match

raw_table = f"{catalog}.bronze.extractions_raw"
print(f"model={chat_model} prompt={PROMPT_VERSION} max_docs={max_docs} workers={workers}")

# COMMAND ----------

spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {raw_table} (
      doc_id STRING, segment_index INT, segment_count INT, model STRING, prompt_version STRING,
      response STRING, error STRING, latency_s DOUBLE, extracted_at TIMESTAMP
    ) COMMENT 'Raw LLM extraction replies, one row per document segment attempt'
    """
)

docs_df = (
    spark.table(f"{catalog}.silver.documents")
    .select("doc_id", "case_name_short", "decision_date", "full_text")
    .orderBy("decision_date", ascending=False)
)
if max_docs:
    docs_df = docs_df.limit(max_docs)
docs = docs_df.collect()

done = {
    (r.doc_id, r.segment_index)
    for r in spark.sql(
        f"""SELECT doc_id, segment_index FROM {raw_table}
            WHERE error IS NULL AND model = '{chat_model}' AND prompt_version = '{PROMPT_VERSION}'"""
    ).collect()
}

tasks = []
for d in docs:
    segments = chunk_text(d.full_text, SEGMENT_CHARS, SEGMENT_OVERLAP)
    for i, seg in enumerate(segments):
        if (d.doc_id, i) not in done:
            tasks.append((d, i, len(segments), seg))
print(f"{len(docs)} documents, {len(tasks)} segments to extract ({len(done)} already done)")

# COMMAND ----------

raw_schema = spark.table(raw_table).schema
w = WorkspaceClient()


def run(task):
    d, i, n, seg = task
    messages = build_messages(d.case_name_short, d.decision_date, seg, i, n)
    try:
        text, secs = call_chat(w, chat_model, messages)
        err = None
    except Exception as e:  # recorded and retried on the next run
        text, secs, err = None, None, f"{type(e).__name__}: {e}"[:2000]
    return (d.doc_id, i, n, chat_model, PROMPT_VERSION, text, err, secs, datetime.now(UTC))


start, batch, completed, failed = time.time(), [], 0, 0
with ThreadPoolExecutor(max_workers=workers) as pool:
    futures = [pool.submit(run, t) for t in tasks]
    for fut in as_completed(futures):
        row = fut.result()
        batch.append(row)
        completed += 1
        failed += row[6] is not None
        if len(batch) >= 25 or completed == len(tasks):
            spark.createDataFrame(batch, raw_schema).write.mode("append").saveAsTable(raw_table)
            batch = []
            rate = completed / (time.time() - start)
            print(f"{completed}/{len(tasks)} segments, {failed} errors, {rate * 60:.1f}/min")

# COMMAND ----------

# MAGIC %md ## Build gold tables from the latest successful reply for each segment

# COMMAND ----------

latest = spark.sql(
    f"""
    SELECT * FROM (
      SELECT *, row_number() OVER (PARTITION BY doc_id, segment_index ORDER BY extracted_at DESC) AS rn
      FROM {raw_table}
      WHERE error IS NULL AND model = '{chat_model}' AND prompt_version = '{PROMPT_VERSION}'
    ) WHERE rn = 1
    """
).collect()

doc_info = {
    r.doc_id: r
    for r in spark.table(f"{catalog}.silver.documents")
    .select("doc_id", "case_name_short", "decision_date", "full_text")
    .collect()
}

by_doc: dict[str, list] = {}
for r in latest:
    by_doc.setdefault(r.doc_id, []).append(r)

entity_rows, event_rows, parse_failures = [], [], 0
for doc_id, replies in by_doc.items():
    info = doc_info.get(doc_id)
    if info is None:
        continue
    source = normalize_for_match(info.full_text)
    seg_entities = []
    for r in sorted(replies, key=lambda r: r.segment_index):
        try:
            parsed = parse_extraction(r.response or "")
        except ValueError:
            parse_failures += 1
            continue
        seg_entities.append(parsed["entities"])
        for j, ev in enumerate(parsed["events"]):
            event_rows.append(
                {
                    "event_id": f"{doc_id}-{r.segment_index:02d}-{j:02d}",
                    "doc_id": doc_id,
                    "case_name_short": info.case_name_short,
                    "decision_date": info.decision_date,
                    "segment_index": r.segment_index,
                    **ev,
                    "quote_verified": quote_is_verbatim(ev["evidence_quote"], source),
                }
            )
    for e in merge_entities(seg_entities):
        entity_rows.append(
            {
                "doc_id": doc_id,
                "case_name_short": info.case_name_short,
                "decision_date": info.decision_date,
                **e,
            }
        )

entity_schema = T.StructType(
    [
        T.StructField("doc_id", T.StringType()),
        T.StructField("case_name_short", T.StringType()),
        T.StructField("decision_date", T.DateType()),
        T.StructField("name", T.StringType()),
        T.StructField("entity_type", T.StringType()),
        T.StructField("role", T.StringType()),
        T.StructField("description", T.StringType()),
        T.StructField("mention_count", T.IntegerType()),
    ]
)
event_schema = T.StructType(
    [
        T.StructField("event_id", T.StringType()),
        T.StructField("doc_id", T.StringType()),
        T.StructField("case_name_short", T.StringType()),
        T.StructField("decision_date", T.DateType()),
        T.StructField("segment_index", T.IntegerType()),
        T.StructField("actor", T.StringType()),
        T.StructField("action", T.StringType()),
        T.StructField("target", T.StringType()),
        T.StructField("event_date", T.DateType()),
        T.StructField("event_date_iso", T.StringType()),
        T.StructField("date_text", T.StringType()),
        T.StructField("description", T.StringType()),
        T.StructField("evidence_quote", T.StringType()),
        T.StructField("quote_verified", T.BooleanType()),
    ]
)

for name, rows, schema, comment in [
    ("entities", entity_rows, entity_schema, "People and organizations named in each opinion"),
    ("events", event_rows, event_schema, "Who did what, when: events extracted from opinions"),
]:
    (
        spark.createDataFrame(rows, schema)
        .write.mode("overwrite")
        .option("overwriteSchema", True)
        .saveAsTable(f"{catalog}.gold.{name}")
    )
    spark.sql(f"COMMENT ON TABLE {catalog}.gold.{name} IS '{comment} (LLM: {chat_model})'")

print(
    f"documents with extractions: {len(by_doc)}  entities: {len(entity_rows)}  "
    f"events: {len(event_rows)}  unparseable replies: {parse_failures}"
)
