#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${PROJECT_ROOT}/config.yaml"

HEADLESS=1
START_ONLY=0
RUN_ONLY=0
STOP_AFTER_RUN=0
NUM_EMULATORS_OVERRIDE=""
RUN_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  scripts/manual_start_and_run_bench.sh [options] -- [run.py args...]

Examples:
  ./scripts/manual_start_and_run_bench.sh -- --mode exec --agents GeneralE2E
  ./scripts/manual_start_and_run_bench.sh --start-only
  ./scripts/manual_start_and_run_bench.sh --run-only -- --task_id 001-FindProductAndFilter
  ./scripts/manual_start_and_run_bench.sh --stop-after-run -- --mode exec
  ./scripts/manual_start_and_run_bench.sh --num-emulators 1 -- --task_id 001-FindProductAndFilter

Options:
  --config PATH       Path to config.yaml. Default: ./config.yaml
  --window            Start emulators with window enabled.
  --headless          Start emulators with -no-window. Default.
  --start-only        Only prepare and start emulators. Do not run benchmark.
  --run-only          Do not start emulators. Reuse already running adb devices.
  --stop-after-run    Kill the emulators started from config after benchmark exits.
  --num-emulators N   Override NUM_OF_EMULATOR from config.yaml for this run.
  -h, --help          Show this help message.

Notes:
  - If cloned AVD copies like MemGUI-AVD-250704_0 do not exist, this script will
    create them once before launching emulators.
  - The benchmark is always run with:
      python run.py --use_existing_devices --auto_confirm_devices ...
    so run.py will not create or terminate emulators for you.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="${2:-}"
      shift 2
      ;;
    --window)
      HEADLESS=0
      shift
      ;;
    --headless)
      HEADLESS=1
      shift
      ;;
    --start-only)
      START_ONLY=1
      shift
      ;;
    --run-only)
      RUN_ONLY=1
      shift
      ;;
    --stop-after-run)
      STOP_AFTER_RUN=1
      shift
      ;;
    --num-emulators)
      NUM_EMULATORS_OVERRIDE="${2:-}"
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

if [[ "${START_ONLY}" -eq 1 && "${RUN_ONLY}" -eq 1 ]]; then
  echo "--start-only and --run-only cannot be used together." >&2
  exit 1
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Config file not found: ${CONFIG_PATH}" >&2
  exit 1
fi

ensure_memgui_env() {
  local conda_root=""
  local candidate=""

  if [[ "${CONDA_DEFAULT_ENV:-}" == "MemGUI" ]]; then
    return 0
  fi

  if [[ -n "${CONDA_EXE:-}" ]]; then
    conda_root="$(dirname "$(dirname "${CONDA_EXE}")")"
  fi

  for candidate in \
    "${conda_root}" \
    "/root/miniconda3" \
    "${HOME}/miniconda3" \
    "${HOME}/anaconda3"
  do
    if [[ -z "${candidate}" ]]; then
      continue
    fi
    if [[ -f "${candidate}/etc/profile.d/conda.sh" ]]; then
      export PATH="${candidate}/bin:${PATH}"
      # shellcheck disable=SC1090
      source "${candidate}/etc/profile.d/conda.sh"
      conda activate MemGUI
      return 0
    fi
  done

  echo "Could not locate conda initialization script for activating MemGUI." >&2
  exit 1
}

ensure_memgui_env

mapfile -t CONFIG_VALUES < <(
  cd "${PROJECT_ROOT}" && python - "${CONFIG_PATH}" <<'PY'
from config_loader import load_config
import sys

cfg = load_config(sys.argv[1], verbose=False)
for key in (
    "EMULATOR_PATH",
    "SOURCE_AVD_NAME",
    "NUM_OF_EMULATOR",
    "SYS_AVD_HOME",
    "SOURCE_AVD_HOME",
    "ANDROID_SDK_PATH",
    "SESSION_ID",
):
    print(cfg[key])
PY
)

EMULATOR_PATH="${CONFIG_VALUES[0]}"
SOURCE_AVD_NAME="${CONFIG_VALUES[1]}"
NUM_OF_EMULATOR="${CONFIG_VALUES[2]}"
SYS_AVD_HOME="${CONFIG_VALUES[3]}"
SOURCE_AVD_HOME="${CONFIG_VALUES[4]}"
ANDROID_SDK_PATH="${CONFIG_VALUES[5]}"
SESSION_ID="${CONFIG_VALUES[6]}"

if [[ -n "${NUM_EMULATORS_OVERRIDE}" ]]; then
  if ! [[ "${NUM_EMULATORS_OVERRIDE}" =~ ^[1-9][0-9]*$ ]]; then
    echo "--num-emulators must be a positive integer." >&2
    exit 1
  fi
  NUM_OF_EMULATOR="${NUM_EMULATORS_OVERRIDE}"
fi

PLATFORM_TOOLS_DIR="$(dirname "$(dirname "${EMULATOR_PATH}")")/platform-tools"
export PATH="${PLATFORM_TOOLS_DIR}:${PATH}"

declare -a EXPECTED_SERIALS=()
for ((idx = 0; idx < NUM_OF_EMULATOR; idx++)); do
  EXPECTED_SERIALS+=("emulator-$((5554 + idx * 2))")
done

collect_online_expected_devices() {
  local adb_output serial
  adb_output="$(adb devices)"
  for serial in "${EXPECTED_SERIALS[@]}"; do
    if awk 'NR > 1 && $2 == "device" {print $1}' <<<"${adb_output}" | grep -qx "${serial}"; then
      echo "${serial}"
    fi
  done
}

collect_expected_device_statuses() {
  local adb_output serial
  adb_output="$(adb devices)"
  for serial in "${EXPECTED_SERIALS[@]}"; do
    awk -v wanted="${serial}" 'NR > 1 && $1 == wanted {print $1 "\t" $2}' <<<"${adb_output}"
  done
}

ensure_avd_copies() {
  local missing_count=0
  local idx

  for ((idx = 0; idx < NUM_OF_EMULATOR; idx++)); do
    if [[ ! -f "${SYS_AVD_HOME}/${SOURCE_AVD_NAME}_${idx}.ini" ]]; then
      missing_count=$((missing_count + 1))
    fi
  done

  if [[ "${missing_count}" -eq 0 ]]; then
    return 0
  fi

  echo "Missing ${missing_count} AVD copy/copies. Preparing cloned AVDs first..."
  (
    cd "${PROJECT_ROOT}"
    NUM_OF_EMULATOR_OVERRIDE="${NUM_OF_EMULATOR}" python - "${CONFIG_PATH}" <<'PY'
import os
from config_loader import load_config
from framework import utils
import sys

cfg = load_config(sys.argv[1], verbose=False)
utils.setup_avd(
    cfg["SYS_AVD_HOME"],
    cfg["SOURCE_AVD_HOME"],
    cfg["SOURCE_AVD_NAME"],
    int(os.environ["NUM_OF_EMULATOR_OVERRIDE"]),
    cfg["ANDROID_SDK_PATH"],
)
PY
  )
}

launch_emulator() {
  local idx="$1"
  local console_port grpc_port serial avd_name log_file
  local -a command

  console_port=$((5554 + idx * 2))
  grpc_port=$((8554 + idx * 2))
  serial="emulator-${console_port}"
  avd_name="${SOURCE_AVD_NAME}_${idx}"
  log_file="/tmp/${avd_name}.log"

  if collect_online_expected_devices | grep -qx "${serial}"; then
    echo "${serial} is already online. Skipping launch."
    return 0
  fi

  command=(
    "${EMULATOR_PATH}"
    -avd "${avd_name}"
    -no-snapshot-save
    -no-audio
    -port "${console_port}"
    -grpc "${grpc_port}"
  )

  if [[ "${HEADLESS}" -eq 1 ]]; then
    command+=(-no-window)
  fi

  if [[ -n "${HTTP_PROXY:-}" ]]; then
    command+=(-http-proxy "${HTTP_PROXY}")
  fi

  echo "Launching ${avd_name} on ${serial} (grpc ${grpc_port})"
  nohup "${command[@]}" >"${log_file}" 2>&1 &
}

wait_for_emulators() {
  local timeout_seconds=600
  local deadline=$((SECONDS + timeout_seconds))
  local online_count ready_count serial boot_completed
  local -a online_devices
  local -a device_statuses
  local unauthorized_warned=0

  while true; do
    mapfile -t online_devices < <(collect_online_expected_devices)
    mapfile -t device_statuses < <(collect_expected_device_statuses)
    online_count="${#online_devices[@]}"
    echo "${online_count}/${#EXPECTED_SERIALS[@]} device(s) launched"
    if [[ "${#device_statuses[@]}" -gt 0 ]]; then
      printf 'Observed adb statuses: %s\n' "${device_statuses[*]}"
    fi
    if [[ "${unauthorized_warned}" -eq 0 ]] && printf '%s\n' "${device_statuses[@]}" | grep -q $'\tunauthorized$'; then
      echo "Detected unauthorized emulator device(s)."
      if [[ "${HEADLESS}" -eq 1 ]]; then
        echo "The emulator likely cold-booted and is waiting for USB debugging authorization."
        echo "Rerun with --window and accept the RSA prompt, or wait for authorization to complete if it resolves automatically."
      fi
      unauthorized_warned=1
    fi
    if [[ "${online_count}" -eq "${#EXPECTED_SERIALS[@]}" ]]; then
      break
    fi
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for emulators to appear in adb devices." >&2
      exit 1
    fi
    sleep 2
  done

  while true; do
    ready_count=0
    for serial in "${EXPECTED_SERIALS[@]}"; do
      boot_completed="$(adb -s "${serial}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
      if [[ "${boot_completed}" == "1" ]]; then
        ready_count=$((ready_count + 1))
      fi
    done
    echo "${#EXPECTED_SERIALS[@]}/${#EXPECTED_SERIALS[@]} device(s) launched; ${ready_count}/${#EXPECTED_SERIALS[@]} device(s) ready"
    if [[ "${ready_count}" -eq "${#EXPECTED_SERIALS[@]}" ]]; then
      break
    fi
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for emulators to finish booting." >&2
      exit 1
    fi
    sleep 2
  done

  echo "All emulators are ready. Waiting 30 seconds for stabilization..."
  sleep 30
}

stop_emulators() {
  local serial
  for serial in "${EXPECTED_SERIALS[@]}"; do
    echo "Stopping ${serial}"
    adb -s "${serial}" emu kill >/dev/null 2>&1 || true
  done
}

adb start-server >/dev/null

if [[ "${RUN_ONLY}" -eq 0 ]]; then
  ensure_avd_copies
  for ((idx = 0; idx < NUM_OF_EMULATOR; idx++)); do
    launch_emulator "${idx}"
  done
  wait_for_emulators
fi

if [[ "${START_ONLY}" -eq 1 ]]; then
  echo "Emulators are ready."
  echo "Run benchmark with:"
  echo "  python run.py --use_existing_devices --auto_confirm_devices --mode exec --agents GeneralE2E"
  exit 0
fi

BENCHMARK_CMD=(python run.py --use_existing_devices --auto_confirm_devices)
if [[ "${#RUN_ARGS[@]}" -gt 0 ]]; then
  BENCHMARK_CMD+=("${RUN_ARGS[@]}")
fi

echo "Session ID: ${SESSION_ID}"
echo "Running benchmark: ${BENCHMARK_CMD[*]}"

benchmark_exit=0
(
  cd "${PROJECT_ROOT}"
  "${BENCHMARK_CMD[@]}"
) || benchmark_exit=$?

if [[ "${STOP_AFTER_RUN}" -eq 1 ]]; then
  stop_emulators
fi

exit "${benchmark_exit}"
