#!/usr/bin/env bash
# Give the CI service principal (`legal-data-demo-ci`) what the prod target needs, beyond the
# catalog grants in sql/00_setup.sql. Run once, as a workspace admin. Safe to re-run.
#
#   - CAN_MANAGE on the SQL warehouse: so a prod deploy can grant the app CAN_USE on it
#   - MANAGE on catalog legal_demo: so a prod deploy can grant the app SELECT on tables/index
#   - CAN_MANAGE on the Vector Search endpoint: so prod pipeline runs can reach it
#   - ownership of the Vector Search index: only an index's owner can sync it, and the prod
#     job (run as this service principal) keeps it in sync. Dev runs then skip the sync.
#
# Usage: scripts/grant_ci.sh
set -euo pipefail

SP="da061def-bd47-4813-82c4-f55e52721e0c"   # legal-data-demo-ci application ID
WAREHOUSE_ID="bcb6defe8c0fdebf"
VS_ENDPOINT="legal-demo-vs"
CATALOG="legal_demo"

acl() { printf '{"access_control_list":[{"service_principal_name":"%s","permission_level":"%s"}]}' "$SP" "$1"; }

echo "warehouse $WAREHOUSE_ID: CAN_MANAGE"
databricks permissions update warehouses "$WAREHOUSE_ID" --json "$(acl CAN_MANAGE)" >/dev/null

VS_ID=$(databricks vector-search-endpoints get-endpoint "$VS_ENDPOINT" -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
echo "vector search endpoint $VS_ENDPOINT: CAN_MANAGE"
databricks permissions update vector-search-endpoints "$VS_ID" --json "$(acl CAN_MANAGE)" >/dev/null

echo "catalog $CATALOG: MANAGE"
databricks grants update catalog "$CATALOG" \
  --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"MANAGE\"]}]}" >/dev/null

INDEX="$CATALOG.silver.chunks_index"
if databricks tables get "$INDEX" >/dev/null 2>&1; then
  echo "index $INDEX: owner"
  databricks tables update "$INDEX" --owner "$SP" >/dev/null
  # The index's update pipeline still runs as whoever created the index (you), so that
  # identity needs MODIFY to write embeddings after the ownership change. MODIFY can't be
  # granted on an index itself, so it goes on the index's schema.
  PIPELINE_ID=$(databricks vector-search-indexes get-index "$INDEX" -o json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["delta_sync_index_spec"]["pipeline_id"])')
  RUN_AS=$(databricks pipelines get "$PIPELINE_ID" -o json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["run_as_user_name"])')
  echo "schema $CATALOG.silver: USE_SCHEMA, SELECT, MODIFY for the index pipeline ($RUN_AS)"
  databricks grants update schema "$CATALOG.silver" \
    --json "{\"changes\":[{\"principal\":\"$RUN_AS\",\"add\":[\"USE_SCHEMA\",\"SELECT\",\"MODIFY\"]}]}" >/dev/null
fi

echo "done"
