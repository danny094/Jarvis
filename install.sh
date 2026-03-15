#!/usr/bin/env bash
set -Eeuo pipefail

# TRION/Jarvis installer
# Supports fresh install + update-in-place via git pull.

REPO_URL="${JARVIS_REPO_URL:-https://github.com/danny094/Jarvis.git}"
BRANCH="${JARVIS_BRANCH:-main}"
INSTALL_DIR="${JARVIS_INSTALL_DIR:-$HOME/Jarvis}"
FORCE_UPDATE="${JARVIS_FORCE_UPDATE:-0}"
SKIP_PREREQS="0"
NO_START="0"
NO_BUILD="0"

TRION_DEFAULT_NETWORK="big-bear-lobe-chat_default"
TRION_DEFAULT_VOLUME="trion_home_data"

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
  --force-update          Force-sync repo to origin/<branch> (discards local git changes)
  --skip-prereqs          Do not install/check OS prerequisites
  --no-build              Skip docker compose build
  --no-start              Do not start stack (only prepare and pull)
  -h, --help              Show this help

Environment variables:
  JARVIS_REPO_URL, JARVIS_BRANCH, JARVIS_INSTALL_DIR, JARVIS_FORCE_UPDATE
  TRION_SHARED_SKILLS_DIR, TRION_PLUGINS_DIR,
  TRION_NVIDIA_SMI_PATH, TRION_NVIDIA_ML_LIB_PATH,
  TRION_NVIDIA_CTL_DEVICE, TRION_NVIDIA0_DEVICE

Examples:
  bash install.sh
  bash install.sh --force-update
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
      --force-update)
        FORCE_UPDATE="1"; shift ;;
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

repo_has_local_changes() {
  if ! git -C "${INSTALL_DIR}" diff --quiet --ignore-submodules --; then
    return 0
  fi
  if ! git -C "${INSTALL_DIR}" diff --cached --quiet --ignore-submodules --; then
    return 0
  fi
  return 1
}

auto_stash_local_changes() {
  local stash_name
  stash_name="jarvis-install-autostash-$(date +%Y%m%d_%H%M%S)"
  warn "Local tracked git changes detected in ${INSTALL_DIR}."
  warn "Creating stash '${stash_name}' so update can continue."
  run_cmd git -C "${INSTALL_DIR}" stash push -m "${stash_name}"
  warn "Local changes were stashed."
  warn "Reapply manually if needed: git -C ${INSTALL_DIR} stash pop"
}

force_update_repo() {
  warn "Force update enabled. Discarding local git changes and syncing to origin/${BRANCH}."
  run_cmd git -C "${INSTALL_DIR}" checkout -f -B "${BRANCH}" "origin/${BRANCH}"
  run_cmd git -C "${INSTALL_DIR}" reset --hard "origin/${BRANCH}"
  run_cmd git -C "${INSTALL_DIR}" clean -fd -e .env
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

    if [[ "${FORCE_UPDATE}" == "1" ]]; then
      force_update_repo
    else
      if repo_has_local_changes; then
        auto_stash_local_changes
      fi

      if ! run_cmd git -C "${INSTALL_DIR}" checkout "${BRANCH}"; then
        err "Failed to checkout branch '${BRANCH}' in ${INSTALL_DIR}."
        err "Rerun with --force-update to discard local git changes and force-sync."
        exit 1
      fi

      if ! run_cmd git -C "${INSTALL_DIR}" pull --ff-only origin "${BRANCH}"; then
        err "Fast-forward update failed for '${BRANCH}'."
        err "If you want a hard sync to origin/${BRANCH}, rerun install with --force-update."
        exit 1
      fi
    fi
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

upsert_env_var() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local tmp_file

  mkdir -p "$(dirname "${env_file}")"
  touch "${env_file}"
  tmp_file="$(mktemp)"

  awk -v k="${key}" -v v="${value}" '
    BEGIN { replaced=0 }
    $0 ~ ("^" k "=") {
      print k "=" v
      replaced=1
      next
    }
    { print }
    END {
      if (!replaced) {
        print k "=" v
      }
    }
  ' "${env_file}" > "${tmp_file}"

  mv "${tmp_file}" "${env_file}"
}

ensure_env_token() {
  local env_file="${INSTALL_DIR}/.env"
  local key="INTERNAL_SECRET_RESOLVE_TOKEN"

  if [[ ! -f "${env_file}" ]] || ! grep -Eq "^${key}=" "${env_file}"; then
    log "Ensuring secure ${key} in .env"
    upsert_env_var "${env_file}" "${key}" "$(random_token)"
  fi
}

ensure_runtime_mount_defaults() {
  local env_file="${INSTALL_DIR}/.env"
  local shared_skills_dir plugins_dir workspace_dir stubs_dir
  local nvidia_smi_path nvidia_ml_path nvidia_ctl_device nvidia0_device

  shared_skills_dir="${TRION_SHARED_SKILLS_DIR:-${INSTALL_DIR}/shared_skills}"
  plugins_dir="${TRION_PLUGINS_DIR:-${HOME:-${INSTALL_DIR}}/.trion/plugins}"
  workspace_dir="${TRION_WORKSPACE_DIR:-/tmp/trion/jarvis/workspace}"
  stubs_dir="${INSTALL_DIR}/scripts/stubs"

  mkdir -p "${shared_skills_dir}" "${plugins_dir}" "${workspace_dir}" "${stubs_dir}"

  if [[ ! -f "${stubs_dir}/nvidia-smi" ]]; then
    cat > "${stubs_dir}/nvidia-smi" <<'EOF'
#!/usr/bin/env bash
echo "NVIDIA-SMI not available in this environment (stub)." >&2
exit 1
EOF
  fi
  if [[ ! -f "${stubs_dir}/libnvidia-ml.so.1" ]]; then
    printf "stub-nvml\n" > "${stubs_dir}/libnvidia-ml.so.1"
  fi
  chmod +x "${stubs_dir}/nvidia-smi" 2>/dev/null || true

  if [[ -x "/usr/bin/nvidia-smi" && -f "/lib/x86_64-linux-gnu/libnvidia-ml.so.1" ]]; then
    nvidia_smi_path="/usr/bin/nvidia-smi"
    nvidia_ml_path="/lib/x86_64-linux-gnu/libnvidia-ml.so.1"
    ok "Detected host NVIDIA runtime files; enabling passthrough mounts."
  else
    nvidia_smi_path="${stubs_dir}/nvidia-smi"
    nvidia_ml_path="${stubs_dir}/libnvidia-ml.so.1"
    warn "Host NVIDIA runtime files not found; using local stubs for portability."
  fi

  if [[ -e "/dev/nvidiactl" && -e "/dev/nvidia0" ]]; then
    nvidia_ctl_device="/dev/nvidiactl"
    nvidia0_device="/dev/nvidia0"
  else
    nvidia_ctl_device="/dev/null"
    nvidia0_device="/dev/null"
    warn "NVIDIA device nodes not found; mapping safe /dev/null fallbacks."
  fi

  upsert_env_var "${env_file}" "TRION_SHARED_SKILLS_DIR" "${shared_skills_dir}"
  upsert_env_var "${env_file}" "TRION_PLUGINS_DIR" "${plugins_dir}"
  upsert_env_var "${env_file}" "TRION_NVIDIA_SMI_PATH" "${nvidia_smi_path}"
  upsert_env_var "${env_file}" "TRION_NVIDIA_ML_LIB_PATH" "${nvidia_ml_path}"
  upsert_env_var "${env_file}" "TRION_NVIDIA_CTL_DEVICE" "${nvidia_ctl_device}"
  upsert_env_var "${env_file}" "TRION_NVIDIA0_DEVICE" "${nvidia0_device}"
}

ensure_external_compose_resources() {
  if ! docker_cmd volume inspect "${TRION_DEFAULT_VOLUME}" >/dev/null 2>&1; then
    log "Creating Docker volume: ${TRION_DEFAULT_VOLUME}"
    docker_cmd volume create "${TRION_DEFAULT_VOLUME}" >/dev/null
  fi

  if ! docker_cmd network inspect "${TRION_DEFAULT_NETWORK}" >/dev/null 2>&1; then
    log "Creating Docker network: ${TRION_DEFAULT_NETWORK}"
    docker_cmd network create "${TRION_DEFAULT_NETWORK}" >/dev/null
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

  ensure_external_compose_resources
  compose_cmd -f "${compose_file}" config >/dev/null

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
  ensure_runtime_mount_defaults
  check_ollama_hint
  start_stack
  print_summary
}

main "$@"
