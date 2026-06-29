#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${PROJECT_ROOT}/config.yaml"

MODEL=""
CONTEXT=""
CONTEXT_MODE="full"

usage() {
  cat <<'EOF'
Usage:
  scripts/set_general_e2e_config.sh --model MODEL --context on|off [--context-mode full|without_task_summary|without_verifier|three_field|four_field] [--config PATH]

Examples:
  ./scripts/set_general_e2e_config.sh --model qwen3.5-plus --context off
  ./scripts/set_general_e2e_config.sh --model kimi-k2 --context on
  ./scripts/set_general_e2e_config.sh --model kimi-k2 --context on --context-mode without_task_summary
  ./scripts/set_general_e2e_config.sh --model kimi-k2 --context on --context-mode without_verifier
  ./scripts/set_general_e2e_config.sh --model kimi-k2 --context on --context-mode three_field
  ./scripts/set_general_e2e_config.sh --config ./config.yaml --model qwen3.5-plus --context on

Notes:
  - This updates top-level config keys used by the GeneralE2E launcher:
      GENERAL_E2E_MODEL
      GENERAL_E2E_ENABLE_MONITOR
      GENERAL_E2E_CONTEXT_MODE
  - It does not edit values under AGENTS:, because those are not used for these
    two runtime switches.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="${2:-}"
      shift 2
      ;;
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

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Config file not found: ${CONFIG_PATH}" >&2
  exit 1
fi

if [[ -z "${MODEL}" ]]; then
  echo "--model is required." >&2
  exit 1
fi

case "${CONTEXT}" in
  on|true|True|TRUE|1)
    CONTEXT_VALUE="true"
    ;;
  off|false|False|FALSE|0)
    CONTEXT_VALUE="false"
    ;;
  *)
    echo "--context must be one of: on, off, true, false, 1, 0" >&2
    exit 1
    ;;
esac

case "${CONTEXT_MODE}" in
  full|complete|without_task_summary|no_task_summary|without_summary|no_summary|without_verifier|no_verifier|without_transition_assessment|no_transition_assessment|three_field|three_fields|minimal|ablation|ablation_3field|3field|four_field|four_fields|ablation_4field|three_field_plus_focus|4field)
    ;;
  *)
    echo "--context-mode must be one of: full, without_task_summary, without_verifier, three_field, four_field" >&2
    exit 1
    ;;
esac

replace_or_append_after() {
  local key="$1"
  local value="$2"
  local anchor="$3"

  if grep -q "^${key}:" "${CONFIG_PATH}"; then
    sed -i "s|^${key}:.*|${key}: ${value}|" "${CONFIG_PATH}"
  else
    sed -i "/^${anchor}:/a ${key}: ${value}" "${CONFIG_PATH}"
  fi
}

replace_or_append_after "GENERAL_E2E_MODEL" "\"${MODEL}\"" "GENERAL_E2E_API_KEY"
replace_or_append_after "GENERAL_E2E_ENABLE_MONITOR" "${CONTEXT_VALUE}" "GENERAL_E2E_MAX_TOKENS"
replace_or_append_after "GENERAL_E2E_CONTEXT_MODE" "\"${CONTEXT_MODE}\"" "GENERAL_E2E_ENABLE_MONITOR"

echo "Updated ${CONFIG_PATH}"
echo "  GENERAL_E2E_MODEL: \"${MODEL}\""
echo "  GENERAL_E2E_ENABLE_MONITOR: ${CONTEXT_VALUE}"
echo "  GENERAL_E2E_CONTEXT_MODE: \"${CONTEXT_MODE}\""
