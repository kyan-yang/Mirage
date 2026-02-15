#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <run_id> [extra modal args]" >&2
  echo "Usage: $0 --run-id <run_id> [extra modal args]" >&2
  echo "Example: $0 abc123 --output-subdir refined_v2 --data-factor 1" >&2
  echo "Example: $0 --run-id abc123 --output-subdir refined_v2 --data-factor 1" >&2
  exit 1
fi

RUN_ID=""
if [[ "${1:-}" == "--run-id" ]]; then
  if [[ $# -lt 2 ]]; then
    echo "Error: --run-id requires a value." >&2
    exit 1
  fi
  RUN_ID="$2"
  shift 2
elif [[ "${1:-}" == --run-id=* ]]; then
  RUN_ID="${1#--run-id=}"
  shift
else
  RUN_ID="$1"
  shift || true
fi

if [[ -z "$RUN_ID" || "$RUN_ID" == -* ]]; then
  echo "Error: missing run_id. Pass '<run_id>' or '--run-id <run_id>'." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PATH="$REPO_ROOT/modal/world-mirror.py"

python3 -m modal run "$SCRIPT_PATH"::refine --run-id "$RUN_ID" "$@"
