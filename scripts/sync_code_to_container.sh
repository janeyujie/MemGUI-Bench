#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTAINER_NAME="memgui-bench"
SRC_DIR="${PROJECT_ROOT}"
DST_DIR=""
SHARED_SRC_DIR="${PROJECT_ROOT}/../general_e2e_agent"
SHARED_DST_DIR="/root/MemGUI-Bench/general_e2e_agent"
SYNC_SHARED=1

usage() {
  cat <<'EOF'
Usage:
  scripts/sync_code_to_container.sh [options]

Examples:
  ./scripts/sync_code_to_container.sh
  ./scripts/sync_code_to_container.sh --container memgui-bench-dev
  ./scripts/sync_code_to_container.sh --container memgui-bench --dst /root/MemGUI-Bench/MemGUI-Bench
  ./scripts/sync_code_to_container.sh --no-shared

Options:
  --container NAME   Running container name. Default: memgui-bench
  --src PATH         Host source repo path. Default: current repo root
  --dst PATH         Container destination path. Auto-detected if omitted
  --shared-src PATH  Host general_e2e_agent repo path. Default: ../general_e2e_agent
  --shared-dst PATH  Container path for general_e2e_agent. Default: /root/MemGUI-Bench/general_e2e_agent
  --no-shared        Do not sync the external general_e2e_agent repo
  -h, --help         Show this help message.

Notes:
  - This is a fallback for existing non-mounted containers.
  - It copies the current working tree into the container using tar streaming.
  - Deleted host files are not removed from the container. For exact one-to-one
    sync, prefer using scripts/start_docker_with_mount.sh instead.
  - The following are excluded by default:
      .git, results, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, .venv
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --container)
      CONTAINER_NAME="${2:-}"
      shift 2
      ;;
    --src)
      SRC_DIR="${2:-}"
      shift 2
      ;;
    --dst)
      DST_DIR="${2:-}"
      shift 2
      ;;
    --shared-src)
      SHARED_SRC_DIR="${2:-}"
      shift 2
      ;;
    --shared-dst)
      SHARED_DST_DIR="${2:-}"
      shift 2
      ;;
    --no-shared)
      SYNC_SHARED=0
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

SRC_DIR="$(cd "${SRC_DIR}" && pwd)"
if [[ "${SYNC_SHARED}" -eq 1 && -d "${SHARED_SRC_DIR}" ]]; then
  SHARED_SRC_DIR="$(cd "${SHARED_SRC_DIR}" && pwd)"
fi

if [[ ! -d "${SRC_DIR}" ]]; then
  echo "Source directory does not exist: ${SRC_DIR}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command not found." >&2
  exit 1
fi

if ! docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "Container not found: ${CONTAINER_NAME}" >&2
  exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}")" != "true" ]]; then
  echo "Container is not running: ${CONTAINER_NAME}" >&2
  exit 1
fi

detect_dst_dir() {
  local candidate
  for candidate in \
    "${DST_DIR}" \
    "/root/MemGUI-Bench" \
    "/root/MemGUI-Bench/MemGUI-Bench"
  do
    if [[ -n "${candidate}" ]] && docker exec "${CONTAINER_NAME}" test -f "${candidate}/run.py"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

if ! RESOLVED_DST="$(detect_dst_dir)"; then
  echo "Could not find repo root inside container." >&2
  echo "Pass --dst explicitly, for example:" >&2
  echo "  --dst /root/MemGUI-Bench" >&2
  echo "  --dst /root/MemGUI-Bench/MemGUI-Bench" >&2
  exit 1
fi

echo "Syncing host repo:"
echo "  ${SRC_DIR}"
echo "to container:"
echo "  ${CONTAINER_NAME}:${RESOLVED_DST}"

TAR_EXCLUDES=(
  --exclude=.git
  --exclude=results
  --exclude=__pycache__
  --exclude=.pytest_cache
  --exclude=.mypy_cache
  --exclude=.ruff_cache
  --exclude=.venv
  --exclude=.idea
  --exclude=.DS_Store
)

(
  cd "${SRC_DIR}"
  tar "${TAR_EXCLUDES[@]}" -cf - .
) | docker exec -i "${CONTAINER_NAME}" tar -xf - -C "${RESOLVED_DST}"

if [[ "${SYNC_SHARED}" -eq 1 ]]; then
  if [[ ! -d "${SHARED_SRC_DIR}" ]]; then
    echo "Shared repo not found, skipping: ${SHARED_SRC_DIR}" >&2
  else
    echo "Syncing shared repo:"
    echo "  ${SHARED_SRC_DIR}"
    echo "to container:"
    echo "  ${CONTAINER_NAME}:${SHARED_DST_DIR}"

    docker exec "${CONTAINER_NAME}" mkdir -p "${SHARED_DST_DIR}"
    (
      cd "${SHARED_SRC_DIR}"
      tar \
        --exclude=.git \
        --exclude=__pycache__ \
        --exclude=.pytest_cache \
        --exclude=.mypy_cache \
        --exclude=.ruff_cache \
        --exclude=.venv \
        --exclude=.idea \
        --exclude=.DS_Store \
        -cf - .
    ) | docker exec -i "${CONTAINER_NAME}" tar -xf - -C "${SHARED_DST_DIR}"
  fi
fi

echo "Sync complete."
