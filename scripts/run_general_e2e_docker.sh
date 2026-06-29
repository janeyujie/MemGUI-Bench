#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONTAINER_NAME="memgui-bench"
CONTAINER_REPO="/root/MemGUI-Bench"
CONTAINER_CONDA_ROOT="/root/miniconda3"
MODEL=""
CONTEXT=""
CONTEXT_MODE="full"
WINDOW=0
STOP_AFTER_RUN=0
DIRECT_RUN=0
NUM_EMULATORS=""
SKIP_SYNC=0
RUN_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/run_general_e2e_docker.sh --model MODEL --context on|off [--context-mode full|without_task_summary|without_verifier|three_field|four_field] [options] -- [run.py args...]

Examples:
  ./scripts/run_general_e2e_docker.sh --model qwen3.5-plus --context off
  ./scripts/run_general_e2e_docker.sh --model qwen3.5-plus --context on -- --task_id 001-FindProductAndFilter
  ./scripts/run_general_e2e_docker.sh --model qwen3.5-plus --context on --context-mode without_task_summary
  ./scripts/run_general_e2e_docker.sh --model qwen3.5-plus --context on --context-mode without_verifier
  ./scripts/run_general_e2e_docker.sh --model qwen3.5-plus --context on --context-mode three_field
  ./scripts/run_general_e2e_docker.sh --model kimi-k2 --context on -- --session_id kimi-context --max_attempts 1

Options:
  --model MODEL        Set GENERAL_E2E_MODEL in config.yaml. Required.
  --context on|off     Set GENERAL_E2E_ENABLE_MONITOR in config.yaml. Required.
  --context-mode MODE   Set GENERAL_E2E_CONTEXT_MODE. Default: full.
  --name NAME          Existing Docker container name. Default: memgui-bench
  --window             Start emulator with GUI window. Default is headless.
  --stop-after-run     Stop emulators after benchmark exits.
  --direct             Run `python run.py` directly instead of the manual emulator wrapper.
  --num-emulators N    Override how many emulators manual_start launches.
  --skip-sync          Do not sync host code into the container before running.
  -h, --help           Show this help message.

Default run.py args:
  --mode exec --agents GeneralE2E --max_attempts 1

Notes:
  - This script reuses an existing container and syncs the current MemGUI-Bench
    workspace into /root/MemGUI-Bench before running.
  - It also syncs ../general_e2e_agent into /root/MemGUI-Bench/general_e2e_agent
    unless --skip-sync is used or the host repo is missing.
  - By default this uses scripts/manual_start_and_run_bench.sh inside the container.
  - Additional benchmark arguments must be placed after `--`.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      MODEL="${2:-}"
      shift 2
      ;;
    --context)
      CONTEXT="${2:-}"
      shift 2
      ;;
    --context-mode)
      CONTEXT_MODE="${2:-}"
      shift 2
      ;;
    --name)
      CONTAINER_NAME="${2:-}"
      shift 2
      ;;
    --window)
      WINDOW=1
      shift
      ;;
    --stop-after-run)
      STOP_AFTER_RUN=1
      shift
      ;;
    --direct)
      DIRECT_RUN=1
      shift
      ;;
    --num-emulators)
      NUM_EMULATORS="${2:-}"
      shift 2
      ;;
    --skip-sync)
      SKIP_SYNC=1
      shift
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

if [[ -z "${MODEL}" ]]; then
  echo "--model is required." >&2
  exit 1
fi

if [[ -z "${CONTEXT}" ]]; then
  echo "--context is required." >&2
  exit 1
fi

if [[ "${#RUN_ARGS[@]}" -eq 0 ]]; then
  RUN_ARGS=(--mode exec --agents GeneralE2E --max_attempts 1)
fi

quote_cmd() {
  local quoted=()
  local arg
  for arg in "$@"; do
    quoted+=("$(printf '%q' "${arg}")")
  done
  printf '%s ' "${quoted[@]}"
}

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
  local explicit_session_id=""
  local session_prefix=""
  local session_suffix=""

  explicit_session_id="$(sed -nE 's/^SESSION_ID:[[:space:]]*"?([^"#]+)"?.*/\1/p' "${config_path}" | head -n 1)"
  if [[ -n "${explicit_session_id}" ]]; then
    printf '%s\n' "${explicit_session_id}"
    return 0
  fi

  session_prefix="$(sed -nE 's/^[[:space:]]*_SESSION_PREFIX:[[:space:]]*"?([^"#]+)"?.*/\1/p' "${config_path}" | head -n 1)"
  session_suffix="$(sed -nE 's/^SESSION_ID_SUFFIX:[[:space:]]*"?([^"#]*)"?.*/\1/p' "${config_path}" | head -n 1)"

  if [[ -z "${session_prefix}" ]]; then
    session_prefix="memgui-"
  fi

  if [[ -n "${session_suffix}" ]]; then
    printf '%s%s\n' "${session_prefix}" "${session_suffix}"
  else
    printf '%sdefault\n' "${session_prefix}"
  fi
}

SESSION_ID_TO_COPY=""
if cli_session_id="$(extract_cli_session_id "${RUN_ARGS[@]}")"; then
  SESSION_ID_TO_COPY="${cli_session_id}"
else
  SESSION_ID_TO_COPY="$(resolve_session_id_from_config "${PROJECT_ROOT}/config.yaml")"
fi

echo "Updating GeneralE2E config..."
"${SCRIPT_DIR}/set_general_e2e_config.sh" \
  --config "${PROJECT_ROOT}/config.yaml" \
  --model "${MODEL}" \
  --context "${CONTEXT}" \
  --context-mode "${CONTEXT_MODE}"

if ! docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "Existing container not found: ${CONTAINER_NAME}" >&2
  exit 1
fi

if [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}")" != "true" ]]; then
  echo "Starting existing container ${CONTAINER_NAME}..."
  docker start "${CONTAINER_NAME}" >/dev/null
fi

if [[ "${SKIP_SYNC}" -eq 0 ]]; then
  echo "Syncing current code into existing container..."
  "${SCRIPT_DIR}/sync_code_to_container.sh" \
    --container "${CONTAINER_NAME}" \
    --src "${PROJECT_ROOT}" \
    --dst "${CONTAINER_REPO}"
else
  echo "Skipping code sync."
fi

if [[ "${DIRECT_RUN}" -eq 1 ]]; then
  INNER_CMD=(python run.py "${RUN_ARGS[@]}")
else
  INNER_CMD=(./scripts/manual_start_and_run_bench.sh)
  if [[ "${WINDOW}" -eq 1 ]]; then
    INNER_CMD+=(--window)
  fi
  if [[ "${STOP_AFTER_RUN}" -eq 1 ]]; then
    INNER_CMD+=(--stop-after-run)
  fi
  if [[ -n "${NUM_EMULATORS}" ]]; then
    INNER_CMD+=(--num-emulators "${NUM_EMULATORS}")
  fi
  INNER_CMD+=(-- "${RUN_ARGS[@]}")
fi

INNER_CMD_STR="$(quote_cmd "${INNER_CMD[@]}")"
CONDA_INIT_STR="export PATH=$(printf '%q' "${CONTAINER_CONDA_ROOT}/bin"):\$PATH && source $(printf '%q' "${CONTAINER_CONDA_ROOT}/etc/profile.d/conda.sh") && conda activate MemGUI"

TTY_ARGS=(-i)
if [[ -t 0 && -t 1 ]]; then
  TTY_ARGS=(-it)
fi

echo
echo "Running inside container ${CONTAINER_NAME}:"
echo "  ${INNER_CMD[*]}"
echo

benchmark_exit=0
docker exec "${TTY_ARGS[@]}" "${CONTAINER_NAME}" bash -lc \
  "${CONDA_INIT_STR} && cd $(printf '%q' "${CONTAINER_REPO}") && ${INNER_CMD_STR}" || benchmark_exit=$?

session_dir_name="${SESSION_ID_TO_COPY}"
if [[ "${session_dir_name}" != session-* ]]; then
  session_dir_name="session-${session_dir_name}"
fi

copy_exit=0
echo
echo "Copying results back to host:"
echo "  ${session_dir_name}"
CONTAINER="${CONTAINER_NAME}" bash "${PROJECT_ROOT}/copy_results.sh" "${session_dir_name}" || copy_exit=$?

if [[ ${benchmark_exit} -ne 0 ]]; then
  exit "${benchmark_exit}"
fi

if [[ ${copy_exit} -ne 0 ]]; then
  exit "${copy_exit}"
fi
