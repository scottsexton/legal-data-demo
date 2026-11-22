#!/usr/bin/env bash
# Copy the shared Python package (src/legal_demo) to the UC Volume the pipeline notebooks
# import from: /Volumes/<catalog>/raw/code/<target>/legal_demo
#
# Usage: scripts/push_code.sh [target] [catalog]     (defaults: dev legal_demo)
#
# Why a Volume: on Databricks Free Edition, notebooks often get "[Errno 5] Input/output error"
# reading bundle workspace files right after a deploy. Volume reads have been reliable.
set -euo pipefail

TARGET="${1:-dev}"
CATALOG="${2:-legal_demo}"
DEST="dbfs:/Volumes/${CATALOG}/raw/code/${TARGET}/legal_demo"
cd "$(dirname "$0")/.."

databricks fs rm -r "$DEST" >/dev/null 2>&1 || true
databricks fs mkdir "$DEST"
for f in src/legal_demo/*.py; do
  databricks fs cp "$f" "$DEST/$(basename "$f")" --overwrite
done
echo "pushed $(ls src/legal_demo/*.py | wc -l | tr -d ' ') files to $DEST"
