#!/usr/bin/env bash
set -Eeuo pipefail

# TRION/Jarvis installer
# Supports fresh install + update-in-place via git pull.

REPO_URL="${JARVIS_REPO_URL:-https://github.com/danny094/Jarvis.git}"
BRANCH="${JARVIS_BRANCH:-main}"
INSTALL_DIR="${JARVIS_INSTALL_DIR:-$HOME/Jarvis}"
SKIP_PREREQS="0"
NO_START="0"
NO_BUILD="0"

COLOR_RED='\033[0;31m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

log() { printf "%b\n" "${COLOR_BLUE}[install]${COLOR_NC} $*"; }
warn() { printf "%b\n" "${COLOR_YELLOW}[warn]${COLOR_NC} $*"; }
err() { printf "%b\n" "${COLOR_RED}[error]${COLOR_NC} $*" >&2; }
ok() { printf "%b\n" "${COLOR_GREEN}[ok]${COLOR_NC} $*"; }

usage() {
  cat <<USAGE
Usage: $0 [options]

Options:
  --repo-url <url>        Git repository URL (default: ${REPO_URL})
  --branch <name>         Git branch/tag to checkout (default: ${BRANCH})
  --install-dir <path>    Install directory (default: ${INSTALL_DIR})
  --skip-prereqs          Do not install/check OS prerequisites
  --no-build              Skip docker compose build
  --no-start              Do not start stack (only prepare and pull)
  -h, --help              Show this help

Environment variables:
  JARVIS_REPO_URL, JARVIS_BRANCH, JARVIS_INSTALL_DIR

Examples:
  bash install.sh
  bash install.sh --install-dir /opt/jarvis
  curl -fsSL https://raw.githubusercontent.com/danny094/Jarvis/main/install.sh | bash
USAGE
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

SUDO=""
if [[ "${EUID}" -ne 0 ]]; then
  if have_cmd sudo; then
    SUDO="sudo"
  fi
fi

DOCKER_BIN="docker"

run_cmd() {
  "$@"
}

run_priv() {
  if [[ -n "${SUDO}" ]]; then
    ${SUDO} "$@"
  else
    "$@"
  fi
}

docker_cmd() {
  if [[ "${DOCKER_BIN}" == "sudo docker" ]]; then
    sudo docker "$@"
  else
    docker "$@"
  fi
}

compose_cmd() {
  if [[ "${DOCKER_BIN}" == "sudo docker" ]]; then
    sudo docker compose "$@"
  else
    docker compose "$@"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo-url)
        REPO_URL="$2"; shift 2 ;;
      --branch)
        BRANCH="$2"; shift 2 ;;
      --install-dir)
        INSTALL_DIR="$2"; shift 2 ;;
      --skip-prereqs)
        SKIP_PREREQS="1"; shift ;;
      --no-start)
        NO_START="1"; shift ;;
      --no-build)
        NO_BUILD="1"; shift ;;
      -h|--help)
        usage; exit 0 ;;
      *)
        err "Unknown option: $1"
        usage
        exit 1 ;;
    esac
  done
}

install_prereqs_debian() {
  log "Installing Debian/Ubuntu prerequisites (git, curl, ca-certificates, gnupg, lsb-release)..."
  run_priv apt-get update -y
  run_priv apt-get install -y ca-certificates curl git gnupg lsb-release

  if ! have_cmd docker; then
    log "Docker not found. Installing Docker Engine via get.docker.com..."
    curl -fsSL https://get.docker.com | run_priv sh
  fi

  # Compose plugin can still be missing on some installs.
  if ! docker compose version >/dev/null 2>&1; then
    log "Installing docker compose plugin..."
    run_priv apt-get install -y docker-compose-plugin || true
  fi
}

ensure_prereqs() {
  if [[ "${SKIP_PREREQS}" == "1" ]]; then
    warn "Skipping prerequisite installation/checks (--skip-prereqs)."
    return
  fi

  if ! have_cmd git || ! have_cmd curl; then
    if have_cmd apt-get; then
      install_prereqs_debian
    else
      err "git/curl missing and no supported package manager detected. Install manually."
      exit 1
    fi
  fi

  if ! have_cmd docker; then
    if have_cmd apt-get; then
      install_prereqs_debian
    else
      err "Docker missing and no supported package manager detected. Install Docker manually."
      exit 1
    fi
  fi

  if ! docker info >/dev/null 2>&1; then
    if [[ -n "${SUDO}" ]] && sudo docker info >/dev/null 2>&1; then
      DOCKER_BIN="sudo docker"
      warn "Using sudo for Docker commands (current user has no direct docker socket access)."
    else
      err "Docker daemon not reachable. Start Docker and retry."
      exit 1
    fi
  fi

  if ! compose_cmd version >/dev/null 2>&1; then
    if have_cmd apt-get; then
      install_prereqs_debian
    fi
  fi

  if ! compose_cmd version >/dev/null 2>&1; then
    err "docker compose plugin not available. Please install Docker Compose plugin."
    exit 1
  fi

  ok "Prerequisites ready."
}

clone_or_update_repo() {
  log "Preparing repository in: ${INSTALL_DIR}"
  mkdir -p "${INSTALL_DIR}"

  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    log "Existing git repository found. Updating..."
    run_cmd git -C "${INSTALL_DIR}" fetch --all --prune
    run_cmd git -C "${INSTALL_DIR}" checkout "${BRANCH}"
    run_cmd git -C "${INSTALL_DIR}" pull --ff-only origin "${BRANCH}"
  elif [[ -d "${INSTALL_DIR}" ]] && [[ -n "$(ls -A "${INSTALL_DIR}" 2>/dev/null || true)" ]]; then
    err "Install directory is not empty and not a git repo: ${INSTALL_DIR}"
    err "Use an empty directory or set --install-dir to another path."
    exit 1
  else
    log "Cloning ${REPO_URL} (${BRANCH}) ..."
    run_cmd git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${INSTALL_DIR}"
  fi

  ok "Repository ready."
}

random_token() {
  if have_cmd openssl; then
    openssl rand -hex 32
  else
    date +%s%N | sha256sum | cut -d' ' -f1
  fi
}

ensure_env_token() {
  local env_file="${INSTALL_DIR}/.env"
  local key="INTERNAL_SECRET_RESOLVE_TOKEN"

  if [[ ! -f "${env_file}" ]]; then
    log "Creating .env with secure internal token"
    printf "%s=%s\n" "${key}" "$(random_token)" > "${env_file}"
    return
  fi

  if ! grep -Eq "^${key}=" "${env_file}"; then
    log "Adding missing ${key} to .env"
    printf "\n%s=%s\n" "${key}" "$(random_token)" >> "${env_file}"
  fi
}

check_ollama_hint() {
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ok "Detected Ollama on host (127.0.0.1:11434)."
  else
    warn "No host Ollama detected on 127.0.0.1:11434."
    warn "If you use external Ollama, ensure it is reachable from Docker on port 11434."
  fi
}

start_stack() {
  local compose_file="${INSTALL_DIR}/docker-compose.yml"

  if [[ ! -f "${compose_file}" ]]; then
    err "docker-compose.yml not found in ${INSTALL_DIR}"
    exit 1
  fi

  if [[ "${NO_BUILD}" == "0" ]]; then
    log "Building containers (this may take a while)..."
    compose_cmd -f "${compose_file}" build
  else
    warn "Skipping build (--no-build)."
  fi

  if [[ "${NO_START}" == "1" ]]; then
    warn "Skipping stack startup (--no-start)."
    return
  fi

  log "Starting TRION stack..."
  compose_cmd -f "${compose_file}" up -d

  log "Waiting for Admin API health..."
  local i
  for i in $(seq 1 45); do
    if curl -fsS --max-time 3 http://127.0.0.1:8200/health >/dev/null 2>&1; then
      ok "Admin API is healthy."
      break
    fi
    sleep 2
  done

  if ! curl -fsS --max-time 3 http://127.0.0.1:8200/health >/dev/null 2>&1; then
    warn "Admin API did not report healthy within timeout."
    warn "Run: docker compose -f ${compose_file} ps"
    warn "Run: docker logs --tail 200 jarvis-admin-api"
  fi
}

print_summary() {
  cat <<SUMMARY

Installation finished.

Path: ${INSTALL_DIR}
WebUI: http://127.0.0.1:8400
Admin API: http://127.0.0.1:8200/health

Useful commands:
  cd ${INSTALL_DIR}
  docker compose -f docker-compose.yml ps
  docker compose -f docker-compose.yml logs -f jarvis-admin-api

SUMMARY
}

main() {
  parse_args "$@"
  ensure_prereqs
  clone_or_update_repo
  ensure_env_token
  check_ollama_hint
  start_stack
  print_summary
}

main "$@"
