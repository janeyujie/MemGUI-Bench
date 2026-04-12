#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COPY_SCRIPT="${SCRIPT_DIR}/copy_results_to_server.sh"
DEFAULT_CONFIG="${PROJECT_ROOT}/config.yaml"

DEST_DIR=""
CONFIG_PATH="${DEFAULT_CONFIG}"
EXPLICIT_SESSION_ID=""
RUN_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/run_and_sync_results.sh --dest /path/on/server [--config /path/to/config.yaml] -- [run.py args...]

Examples:
  ./scripts/run_and_sync_results.sh --dest /data/memgui-results -- --mode exec --agents GeneralE2E
  ./scripts/run_and_sync_results.sh --dest /data/memgui-results -- --session_id memgui-my-test
  ./scripts/run_and_sync_results.sh --dest /data/memgui-results --config ./config.yaml -- --task_id 001-FindProductAndFilter

Wrapper options:
  --dest PATH         Destination directory on the current server. Required.
  --config PATH       Config file to read when inferring session_id. Default: ./config.yaml
  --session-id ID     Force the session_id used for the post-run sync.
  -h, --help          Show this help message.

Notes:
  - Put benchmark arguments after `--`.
  - If session_id is not passed explicitly, the script tries:
    1. `--session_id` from run.py args
    2. config.yaml-derived session_id
    3. latest results session as fallback
  - Sync is attempted even if the benchmark run fails, so partial results are preserved.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      DEST_DIR="${2:-}"
      shift 2
      ;;
    --config)
      CONFIG_PATH="${2:-}"
      shift 2
      ;;
    --session-id)
      EXPLICIT_SESSION_ID="${2:-}"
      shift 2
      ;;
    --)
      shift
      RUN_ARGS=("$@")
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${DEST_DIR}" ]]; then
  echo "--dest is required." >&2
  usage >&2
  exit 1
fi

if [[ ! -x "${COPY_SCRIPT}" ]]; then
  echo "Copy script not found or not executable: ${COPY_SCRIPT}" >&2
  exit 1
fi

extract_cli_session_id() {
  local args=("$@")
  local i=0
  while [[ $i -lt ${#args[@]} ]]; do
    case "${args[$i]}" in
      --session_id)
        if [[ $((i + 1)) -lt ${#args[@]} ]]; then
          printf '%s\n' "${args[$((i + 1))]}"
          return 0
        fi
        ;;
      --session_id=*)
        printf '%s\n' "${args[$i]#*=}"
        return 0
        ;;
    esac
    i=$((i + 1))
  done
  return 1
}

resolve_session_id_from_config() {
  local config_path="$1"
  if [[ ! -f "${config_path}" ]]; then
    return 1
  fi

  python - "${config_path}" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except Exception:
    sys.exit(1)

config_path = Path(sys.argv[1])
try:
    config = yaml.safe_load(config_path.read_text()) or {}
except Exception:
    sys.exit(1)

session_id = config.get("SESSION_ID")
if session_id:
    print(session_id)
    sys.exit(0)

run_presets = (((config.get("_MODE_PRESETS") or {}).get("run")) or {})
session_prefix = run_presets.get("_SESSION_PREFIX", "memgui-")
session_suffix = config.get("SESSION_ID_SUFFIX", "")

if session_suffix:
    print(f"{session_prefix}{session_suffix}")
else:
    print(f"{session_prefix}default")
PY
}

SESSION_ID_TO_COPY=""
if [[ -n "${EXPLICIT_SESSION_ID}" ]]; then
  SESSION_ID_TO_COPY="${EXPLICIT_SESSION_ID}"
else
  if cli_session_id="$(extract_cli_session_id "${RUN_ARGS[@]}")"; then
    SESSION_ID_TO_COPY="${cli_session_id}"
  elif config_session_id="$(resolve_session_id_from_config "${CONFIG_PATH}" 2>/dev/null)"; then
    SESSION_ID_TO_COPY="${config_session_id}"
  fi
fi

echo "Running benchmark from: ${PROJECT_ROOT}"
if [[ ${#RUN_ARGS[@]} -eq 0 ]]; then
  echo "Benchmark command: python run.py"
else
  echo "Benchmark command: python run.py ${RUN_ARGS[*]}"
fi

benchmark_exit=0
(
  cd "${PROJECT_ROOT}"
  python run.py "${RUN_ARGS[@]}"
) || benchmark_exit=$?

sync_exit=0
if [[ -n "${SESSION_ID_TO_COPY}" ]]; then
  echo "Syncing session: ${SESSION_ID_TO_COPY}"
  "${COPY_SCRIPT}" --dest "${DEST_DIR}" --session-id "${SESSION_ID_TO_COPY}" || sync_exit=$?
else
  echo "Could not infer session_id. Falling back to latest session."
  "${COPY_SCRIPT}" --dest "${DEST_DIR}" --latest || sync_exit=$?
fi

if [[ ${benchmark_exit} -ne 0 ]]; then
  echo "Benchmark finished with non-zero exit code: ${benchmark_exit}" >&2
fi

if [[ ${sync_exit} -ne 0 ]]; then
  echo "Result sync failed with exit code: ${sync_exit}" >&2
fi

if [[ ${benchmark_exit} -ne 0 ]]; then
  exit "${benchmark_exit}"
fi

if [[ ${sync_exit} -ne 0 ]]; then
  exit "${sync_exit}"
fi

echo "Run and sync completed successfully."
