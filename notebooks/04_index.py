# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Vector Search index on `silver.chunks`
# MAGIC Creates (or syncs) a Delta Sync index whose embeddings Databricks computes with the
# MAGIC embedding model endpoint, then runs a test query.
# MAGIC
# MAGIC Only the index's owner can sync it. The prod job's service principal owns it, so in the
# MAGIC dev target (your own login) the sync is skipped and the existing index is just checked.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-vectorsearch
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "legal_demo")
dbutils.widgets.text("embedding_model", "databricks-gte-large-en")
dbutils.widgets.text("vs_endpoint", "legal-demo-vs")
dbutils.widgets.text("target", "dev")
catalog = dbutils.widgets.get("catalog")
embedding_model = dbutils.widgets.get("embedding_model")
endpoint_name = dbutils.widgets.get("vs_endpoint")
target = dbutils.widgets.get("target")

import time

from databricks.vector_search.client import VectorSearchClient

source_table = f"{catalog}.silver.chunks"
index_name = f"{catalog}.silver.chunks_index"
vsc = VectorSearchClient(disable_notice=True)

# COMMAND ----------

existing = [e["name"] for e in vsc.list_endpoints().get("endpoints", [])]
if endpoint_name not in existing:
    print(f"creating endpoint {endpoint_name}")
    vsc.create_endpoint(name=endpoint_name, endpoint_type="STANDARD")

for _ in range(90):  # up to ~30 minutes
    state = vsc.get_endpoint(endpoint_name).get("endpoint_status", {}).get("state")
    print("endpoint state:", state)
    if state == "ONLINE":
        break
    time.sleep(20)
else:
    raise TimeoutError(f"endpoint {endpoint_name} not ONLINE")

# COMMAND ----------


def wait_until_synced(index, timeout_s=5000, poll_s=30):
    """Poll until the index is ONLINE with no pending update.

    (The client's own wait_until_ready compares a timedelta to an int and crashes.)
    A brand-new index first waits for the endpoint's compute (PROVISIONING_ENDPOINT).
    """
    # The first build embeds every chunk and is slow on Free Edition (~100-200 chunks/min).
    # Later syncs only embed changed chunks. The task itself times out at 5400s.
    start = time.time()
    while True:
        status = index.describe().get("status", {})
        state = status.get("detailed_state", "")
        print(f"[{int(time.time() - start):>5}s] {state}  {status.get('message', '')[:120]}")
        if "FAILED" in state:
            raise RuntimeError(f"index failed: {status}")
        if state == "ONLINE_NO_PENDING_UPDATE":
            return status
        if time.time() - start > timeout_s:
            raise TimeoutError(f"index not synced after {timeout_s}s: {state}")
        time.sleep(poll_s)


existing_indexes = [i["name"] for i in vsc.list_indexes(endpoint_name).get("vector_indexes", [])]
if index_name in existing_indexes:
    index = vsc.get_index(endpoint_name, index_name)
    wait_until_synced(index)  # finish any build or sync already in progress
    try:
        index.sync()
        print("syncing existing index")
        time.sleep(30)  # let the sync register before polling
    except Exception as e:
        if "PERMISSION_DENIED" not in str(e) or target == "prod":
            raise
        try:
            from databricks.sdk import WorkspaceClient

            owner = WorkspaceClient().tables.get(index_name).owner
        except Exception:
            owner = "another principal"
        print(f"skipping sync: the index is owned by {owner}, and only its owner can sync it.")
        print("Run the prod job to sync it. Checking the existing index instead.")
else:
    print("creating index")
    index = vsc.create_delta_sync_index(
        endpoint_name=endpoint_name,
        index_name=index_name,
        source_table_name=source_table,
        pipeline_type="TRIGGERED",
        primary_key="chunk_id",
        embedding_source_column="text",
        embedding_model_endpoint_name=embedding_model,
        columns_to_sync=[
            "chunk_id",
            "doc_id",
            "chunk_index",
            "case_name_short",
            "decision_date",
            "text",
        ],
    )

status = wait_until_synced(index)
print("indexed rows:", status.get("indexed_row_count"))

# COMMAND ----------

results = index.similarity_search(
    query_text="Who was convicted of murder and what did the court decide on appeal?",
    columns=["chunk_id", "case_name_short", "decision_date", "text"],
    num_results=3,
)
for row in results["result"]["data_array"]:
    print(row[1], row[2], "score", round(row[-1], 3), "|", row[3][:200].replace("\n", " "))
