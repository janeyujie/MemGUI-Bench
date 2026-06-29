#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

IMAGE="crpi-6p9eo5da91i2tx5v.cn-hangzhou.personal.cr.aliyuncs.com/memgui/memgui-bench:26020301"
CONTAINER_NAME="memgui-bench-dev"
HOST_REPO="${PROJECT_ROOT}"
CONTAINER_REPO="/root/MemGUI-Bench/MemGUI-Bench"
HOST_SHARED_REPO="${PROJECT_ROOT}/../general_e2e_agent"
CONTAINER_SHARED_REPO="/root/MemGUI-Bench/general_e2e_agent"
ATTACH=0
FORCE_RECREATE=0

usage() {
  cat <<'EOF'
Usage:
  scripts/start_docker_with_mount.sh [options]

Examples:
  ./scripts/start_docker_with_mount.sh
  ./scripts/start_docker_with_mount.sh --attach
  ./scripts/start_docker_with_mount.sh --name memgui-bench --force-recreate

Options:
  --name NAME            Docker container name. Default: memgui-bench-dev
  --image IMAGE          Docker image to use.
  --host-repo PATH       Host repo path to mount. Default: current repo root
  --container-repo PATH  Container mount target. Default: /root/MemGUI-Bench/MemGUI-Bench
  --shared-repo PATH     Optional external general_e2e_agent repo path. Default: ../general_e2e_agent
  --attach               Start/reuse container and open an interactive shell.
  --force-recreate       Remove existing container with the same name first.
  -h, --help             Show this help message.

Notes:
  - This runs the container in detached mode with `sleep infinity`.
  - The whole repo is bind-mounted, so host code changes are immediately visible
    inside the container. This is the recommended workflow for development.
  - If ../general_e2e_agent exists, it is also mounted automatically to
    /root/MemGUI-Bench/general_e2e_agent for the shared GeneralE2E implementation.
  - Results written under ./results also stay on the host because the repo is
    mounted as a whole.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      CONTAINER_NAME="${2:-}"
      shift 2
      ;;
    --image)
      IMAGE="${2:-}"
      shift 2
      ;;
    --host-repo)
      HOST_REPO="${2:-}"
      shift 2
      ;;
    --container-repo)
      CONTAINER_REPO="${2:-}"
      shift 2
      ;;
    --shared-repo)
      HOST_SHARED_REPO="${2:-}"
      shift 2
      ;;
    --attach)
      ATTACH=1
      shift
      ;;
    --force-recreate)
      FORCE_RECREATE=1
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

HOST_REPO="$(cd "${HOST_REPO}" && pwd)"
if [[ -d "${HOST_SHARED_REPO}" ]]; then
  HOST_SHARED_REPO="$(cd "${HOST_SHARED_REPO}" && pwd)"
else
  HOST_SHARED_REPO=""
fi

if [[ ! -d "${HOST_REPO}" ]]; then
  echo "Host repo does not exist: ${HOST_REPO}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command not found." >&2
  exit 1
fi

container_exists=0
container_running=0
existing_workdir=""
existing_mount_dest=""
existing_shared_mount_dest=""

if docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  container_exists=1
  if [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}")" == "true" ]]; then
    container_running=1
  fi
  existing_workdir="$(docker inspect -f '{{.Config.WorkingDir}}' "${CONTAINER_NAME}")"
  existing_mount_dest="$(docker inspect -f '{{range .Mounts}}{{if eq .Source "'"${HOST_REPO}"'"}}{{.Destination}}{{end}}{{end}}' "${CONTAINER_NAME}")"
  if [[ -n "${HOST_SHARED_REPO}" ]]; then
    existing_shared_mount_dest="$(docker inspect -f '{{range .Mounts}}{{if eq .Source "'"${HOST_SHARED_REPO}"'"}}{{.Destination}}{{end}}{{end}}' "${CONTAINER_NAME}")"
  fi
fi

if [[ "${container_exists}" -eq 1 && "${FORCE_RECREATE}" -eq 1 ]]; then
  if [[ "${container_running}" -eq 1 ]]; then
    echo "Stopping existing container: ${CONTAINER_NAME}"
    docker stop "${CONTAINER_NAME}" >/dev/null
  fi
  echo "Removing existing container: ${CONTAINER_NAME}"
  docker rm "${CONTAINER_NAME}" >/dev/null
  container_exists=0
  container_running=0
fi

if [[ "${container_exists}" -eq 1 && "${FORCE_RECREATE}" -eq 0 ]]; then
  if [[ "${existing_workdir}" != "${CONTAINER_REPO}" || "${existing_mount_dest}" != "${CONTAINER_REPO}" ]]; then
    echo "Existing container path does not match requested path." >&2
    echo "  Container name: ${CONTAINER_NAME}" >&2
    echo "  Existing working dir: ${existing_workdir:-<empty>}" >&2
    echo "  Existing mount dest: ${existing_mount_dest:-<empty>}" >&2
    echo "  Requested path: ${CONTAINER_REPO}" >&2
    echo "Rerun with --force-recreate to rebuild the container with the correct path." >&2
    exit 1
  fi
  if [[ -n "${HOST_SHARED_REPO}" && "${existing_shared_mount_dest}" != "${CONTAINER_SHARED_REPO}" ]]; then
    echo "Existing container is missing the required shared general_e2e_agent mount." >&2
    echo "  Container name: ${CONTAINER_NAME}" >&2
    echo "  Host shared repo: ${HOST_SHARED_REPO}" >&2
    echo "  Existing shared mount dest: ${existing_shared_mount_dest:-<empty>}" >&2
    echo "  Required shared mount dest: ${CONTAINER_SHARED_REPO}" >&2
    echo "Rerun with --force-recreate to rebuild the container with the shared repo mounted." >&2
    exit 1
  fi
fi

if [[ "${container_exists}" -eq 0 ]]; then
  echo "Starting container ${CONTAINER_NAME}"
  DOCKER_RUN_CMD=(
    docker run -d --privileged
    --name "${CONTAINER_NAME}"
    -w "${CONTAINER_REPO}"
    -v "${HOST_REPO}:${CONTAINER_REPO}"
  )
  if [[ -n "${HOST_SHARED_REPO}" ]]; then
    DOCKER_RUN_CMD+=(-v "${HOST_SHARED_REPO}:${CONTAINER_SHARED_REPO}")
  fi
  DOCKER_RUN_CMD+=("${IMAGE}" sleep infinity)
  "${DOCKER_RUN_CMD[@]}" >/dev/null
  container_running=1
elif [[ "${container_running}" -eq 0 ]]; then
  echo "Starting existing stopped container: ${CONTAINER_NAME}"
  docker start "${CONTAINER_NAME}" >/dev/null
  container_running=1
else
  echo "Container ${CONTAINER_NAME} is already running."
fi

echo
echo "Mounted host repo:"
echo "  ${HOST_REPO}"
echo "to container path:"
echo "  ${CONTAINER_REPO}"
if [[ -n "${HOST_SHARED_REPO}" ]]; then
  echo
  echo "Mounted shared repo:"
  echo "  ${HOST_SHARED_REPO}"
  echo "to container path:"
  echo "  ${CONTAINER_SHARED_REPO}"
fi
echo
echo "Useful commands:"
echo "  docker exec -it ${CONTAINER_NAME} bash"
echo "  docker exec -it ${CONTAINER_NAME} bash -lc 'cd ${CONTAINER_REPO} && python run.py'"
echo "  docker exec -it ${CONTAINER_NAME} bash -lc 'cd ${CONTAINER_REPO} && python run.py --agents GeneralE2E --max_attempts 1'"

if [[ "${ATTACH}" -eq 1 ]]; then
  exec docker exec -it "${CONTAINER_NAME}" bash -lc "cd '${CONTAINER_REPO}' && exec bash"
fi
