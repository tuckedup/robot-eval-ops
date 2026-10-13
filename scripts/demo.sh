#!/usr/bin/env bash
# One-command offline demo (MOCK fixture backend by default; `sim` for PyBullet Panda physics).
# Usage: scripts/demo.sh [mock|sim]
set -euo pipefail
cd "$(dirname "$0")/.."
BACKEND="${1:-mock}"
robotevalops demo run --backend "$BACKEND" --home "data/demo_${BACKEND}"
echo "Reports: data/demo_${BACKEND}/reports/<session_id>/report.html"
