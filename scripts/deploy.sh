#!/usr/bin/env bash
# Deploy everything for a bundle target: shared code to the Volume, then the bundle.
# Usage: scripts/deploy.sh [target]    (default: dev)
set -euo pipefail
TARGET="${1:-dev}"
cd "$(dirname "$0")/.."
scripts/push_code.sh "$TARGET"
databricks bundle deploy -t "$TARGET"
