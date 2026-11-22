#!/usr/bin/env bash
# Fail unless a Databricks App is running and its latest deployment succeeded.
# Usage: scripts/check_app.sh [app-name]     (default: legal-demo)
set -euo pipefail
APP="${1:-legal-demo}"
databricks apps get "$APP" -o json | python3 -c '
import json, sys
app = json.load(sys.stdin)
compute = (app.get("compute_status") or {}).get("state")
status = (app.get("app_status") or {}).get("state")
deployment = ((app.get("active_deployment") or {}).get("status") or {}).get("state")
name = app["name"]
print(f"{name}: compute={compute} app={status} deployment={deployment}")
print(app.get("url", ""))
ok = compute == "ACTIVE" and status == "RUNNING" and deployment == "SUCCEEDED"
sys.exit(0 if ok else 1)
'
