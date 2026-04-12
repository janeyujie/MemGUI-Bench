#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${PROJECT_ROOT}/results"

DEST_DIR=""
SESSION_ID=""
COPY_ALL=0
USE_LATEST=0

usage() {
  cat <<'EOF'
Usage:
  scripts/copy_results_to_server.sh --dest /path/on/server [--session-id memgui-xxx]
  scripts/copy_results_to_server.sh --dest /path/on/server --latest
  scripts/copy_results_to_server.sh --dest /path/on/server --all

Options:
  --dest PATH         Destination directory on the current server. Required.
  --session-id ID     Copy only results/session-ID
  --latest            Copy the most recently modified session directory
  --all               Copy all session-* directories plus top-level result files
  -h, --help          Show this help message

Notes:
  - If you are inside Docker, PATH should be a mounted directory on the host/server.
  - If your repo itself is mounted from the host, you may not need this script at all,
    because results are already written to the host filesystem.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      DEST_DIR="${2:-}"
      shift 2
      ;;
    --session-id)
      SESSION_ID="${2:-}"
      shift 2
      ;;
    --latest)
      USE_LATEST=1
      shift
      ;;
    --all)
      COPY_ALL=1
      shift
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

if [[ ! -d "${RESULTS_DIR}" ]]; then
  echo "Results directory does not exist: ${RESULTS_DIR}" >&2
  exit 1
fi

mode_count=0
[[ -n "${SESSION_ID}" ]] && ((mode_count += 1))
[[ "${USE_LATEST}" -eq 1 ]] && ((mode_count += 1))
[[ "${COPY_ALL}" -eq 1 ]] && ((mode_count += 1))

if [[ "${mode_count}" -gt 1 ]]; then
  echo "Use only one of --session-id, --latest, or --all." >&2
  exit 1
fi

mkdir -p "${DEST_DIR}"

copy_item() {
  local src="$1"
  local dst="$2"

  if command -v rsync >/dev/null 2>&1; then
    rsync -a "${src}" "${dst}"
  else
    cp -a "${src}" "${dst}"
  fi
}

copy_session_dir() {
  local session_dir="$1"
  local session_name
  session_name="$(basename "${session_dir}")"

  echo "Copying ${session_name} -> ${DEST_DIR}/"
  copy_item "${session_dir}" "${DEST_DIR}/"
}

if [[ "${COPY_ALL}" -eq 1 ]]; then
  shopt -s nullglob
  session_dirs=("${RESULTS_DIR}"/session-*)
  shopt -u nullglob

  if [[ "${#session_dirs[@]}" -eq 0 ]]; then
    echo "No session directories found under ${RESULTS_DIR}" >&2
    exit 1
  fi

  for session_dir in "${session_dirs[@]}"; do
    copy_session_dir "${session_dir}"
  done

  shopt -s nullglob
  top_level_files=(
    "${RESULTS_DIR}"/*.zip
    "${RESULTS_DIR}"/*.json
    "${RESULTS_DIR}"/*.csv
  )
  shopt -u nullglob

  for file in "${top_level_files[@]}"; do
    echo "Copying $(basename "${file}") -> ${DEST_DIR}/"
    copy_item "${file}" "${DEST_DIR}/"
  done

  echo "Done."
  exit 0
fi

if [[ "${USE_LATEST}" -eq 1 ]]; then
  latest_session="$(find "${RESULTS_DIR}" -maxdepth 1 -mindepth 1 -type d -name 'session-*' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
  if [[ -z "${latest_session}" ]]; then
    echo "No session directories found under ${RESULTS_DIR}" >&2
    exit 1
  fi
  copy_session_dir "${latest_session}"
  echo "Done."
  exit 0
fi

if [[ -n "${SESSION_ID}" ]]; then
  session_path="${RESULTS_DIR}/session-${SESSION_ID}"
  if [[ ! -d "${session_path}" ]]; then
    session_path="${RESULTS_DIR}/${SESSION_ID}"
  fi

  if [[ ! -d "${session_path}" ]]; then
    echo "Session directory not found for: ${SESSION_ID}" >&2
    exit 1
  fi

  copy_session_dir "${session_path}"
  echo "Done."
  exit 0
fi

echo "No copy mode provided. Defaulting to latest session."
latest_session="$(find "${RESULTS_DIR}" -maxdepth 1 -mindepth 1 -type d -name 'session-*' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
if [[ -z "${latest_session}" ]]; then
  echo "No session directories found under ${RESULTS_DIR}" >&2
  exit 1
fi
copy_session_dir "${latest_session}"
echo "Done."
