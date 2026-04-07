#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

MODE="check"
OUT_DIR=""

usage() {
  cat <<'USAGE'
Usage: scripts/ops/sanitize_for_publish.sh [OPTIONS]

Modes:
  --check                 Check tracked files for publish-sensitive content [default]
  --export <dir>          Create a sanitized tracked-file export in <dir>

Options:
  --repo-root <dir>       Override repository root
  -h, --help              Show this help

Notes:
  - The script only inspects tracked files via git.
  - Runtime data, logs and local secrets are excluded from export output.
  - The source worktree is never modified.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      MODE="check"
      shift
      ;;
    --export)
      MODE="export"
      OUT_DIR="${2:-}"
      if [[ -z "${OUT_DIR}" ]]; then
        echo "--export requires a target directory" >&2
        exit 2
      fi
      shift 2
      ;;
    --repo-root)
      REPO_ROOT="${2:-}"
      if [[ -z "${REPO_ROOT}" ]]; then
        echo "--repo-root requires a path" >&2
        exit 2
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "${REPO_ROOT}"

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Not a git repository: ${REPO_ROOT}" >&2
  exit 2
fi

is_sensitive_path() {
  local path="$1"
  case "${path}" in
    .env|.env.*)
      [[ "${path}" == ".env.example" ]] && return 1
      return 0
      ;;
    logs/*|backups/*|snapshots/*)
      return 0
      ;;
    memory/*|memory_speicher/*)
      return 0
      ;;
    docs/session-handoff*.md)
      return 0
      ;;
    *.bak.*)
      return 0
      ;;
    .tmp_gaming_inspect/*)
      return 0
      ;;
    *.db|*.sqlite|*.sqlite3|*.db-journal|*.jsonl|*.ndjson)
      return 0
      ;;
    */conversation_container_state.json|conversation_container_state.json)
      return 0
      ;;
    */__pycache__/*|*.pyc|*.pyo)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

tracked_matches() {
  git ls-files | while IFS= read -r path; do
    if is_sensitive_path "${path}"; then
      printf '%s\n' "${path}"
    fi
  done
}

print_report() {
  local matches="$1"
  if [[ -z "${matches}" ]]; then
    echo "[publish-check] No tracked sensitive files matched the denylist."
    return 0
  fi
  echo "[publish-check] Tracked files that should not be shipped as public runtime data:"
  printf '%s\n' "${matches}" | sed 's/^/  - /'
}

matches="$(tracked_matches || true)"

if [[ "${MODE}" == "check" ]]; then
  print_report "${matches}"
  if [[ -n "${matches}" ]]; then
    exit 1
  fi
  exit 0
fi

mkdir -p "${OUT_DIR}"
OUT_DIR="$(cd "${OUT_DIR}" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

git archive --format=tar HEAD | tar -xf - -C "${tmp_dir}"

while IFS= read -r path; do
  [[ -z "${path}" ]] && continue
  rm -rf "${tmp_dir}/${path}"
done <<< "${matches}"

find "${tmp_dir}" -depth -type d -empty -delete

rm -rf "${OUT_DIR}"
mkdir -p "$(dirname "${OUT_DIR}")"
mv "${tmp_dir}" "${OUT_DIR}"
trap - EXIT

echo "[publish-export] Created sanitized export at ${OUT_DIR}"
print_report "${matches}"
