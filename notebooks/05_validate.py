# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Validate the loaded data
# MAGIC Row counts, nulls, extraction coverage, and how many event quotes appear verbatim in the
# MAGIC opinion text. Fails the job if anything is badly off.

# COMMAND ----------

dbutils.widgets.text("catalog", "legal_demo")
dbutils.widgets.text("max_docs", "0")
catalog = dbutils.widgets.get("catalog")
max_docs = int(dbutils.widgets.get("max_docs") or 0)


def q(sql):
    return spark.sql(sql.format(c=catalog)).collect()


# COMMAND ----------

counts = {
    t: q(f"SELECT count(*) AS n FROM {{c}}.{t}")[0].n
    for t in [
        "bronze.documents_raw",
        "silver.documents",
        "silver.chunks",
        "bronze.extractions_raw",
        "gold.entities",
        "gold.events",
    ]
}
for t, n in counts.items():
    print(f"{t:26s} {n:>7,}")

docs = q(
    """SELECT count(*) n, count_if(decision_date IS NULL) no_date, count_if(char_count < 1000) short,
              count(DISTINCT doc_id) uniq FROM {c}.silver.documents"""
)[0]
orphans = q(
    """SELECT count(*) n FROM {c}.silver.chunks ch
       LEFT ANTI JOIN {c}.silver.documents d ON ch.doc_id = d.doc_id"""
)[0].n
covered = q("SELECT count(DISTINCT doc_id) n FROM {c}.gold.events")[0].n
errors = q("SELECT count(*) n FROM {c}.bronze.extractions_raw WHERE error IS NOT NULL")[0].n
ev = q(
    """SELECT count(*) n, avg(CAST(quote_verified AS INT)) verified,
              avg(CAST(event_date IS NOT NULL AS INT)) dated,
              count_if(actor IS NULL) no_actor FROM {c}.gold.events"""
)[0]

print(
    f"\ndocuments: {docs.n} (unique {docs.uniq}), missing date: {docs.no_date}, <1k chars: {docs.short}"
)
print(f"chunks without a document: {orphans}")
print(f"documents with events: {covered}/{docs.n}   failed LLM calls (all attempts): {errors}")
print(
    f"events: {ev.n:,}  quote verified: {ev.verified or 0:.0%}  "
    f"with full date: {ev.dated or 0:.0%}  missing actor: {ev.no_actor}"
)

# COMMAND ----------

print("Most common entity roles:")
for r in q(
    "SELECT lower(role) role, count(*) n FROM {c}.gold.entities GROUP BY 1 ORDER BY n DESC LIMIT 12"
):
    print(f"  {r.n:>5}  {r.role}")

print("\nSample of 10 events (random):")
for r in q(
    """SELECT case_name_short, event_date_iso, actor, action, target, quote_verified, evidence_quote
       FROM {c}.gold.events ORDER BY rand(42) LIMIT 10"""
):
    mark = "✓" if r.quote_verified else "?"
    print(
        f"  {mark} [{r.case_name_short}] {r.event_date_iso or '----'} {r.actor} | {r.action} | {r.target}"
    )
    print(f'      "{(r.evidence_quote or "")[:160]}"')

# COMMAND ----------

expected_docs = max_docs or docs.n
problems = []
if docs.n == 0 or docs.uniq != docs.n:
    problems.append("silver.documents is empty or has duplicate doc_ids")
if orphans:
    problems.append(f"{orphans} chunks reference missing documents")
if covered < 0.9 * expected_docs:
    problems.append(f"only {covered} of {expected_docs} documents have events")
if ev.n and (ev.verified or 0) < 0.6:
    problems.append(f"only {ev.verified:.0%} of event quotes are verbatim")
assert not problems, "Validation failed: " + "; ".join(problems)
print("Validation passed")
