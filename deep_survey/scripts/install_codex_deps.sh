#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEEP_SURVEY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-"${HOME}/.codex"}"
SKILLS_DIR="${CODEX_HOME}/skills"
PLUGIN_CACHE_DIR="${CODEX_HOME}/plugins/cache/deep-research-local/deep-literature-workflow/0.1.0"
WORKSPACE_PLUGIN_DIR="${DEEP_SURVEY_DIR}/plugins/deep-literature-workflow"

install_dir() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -d "${src}" ]]; then
    echo "missing bundled ${label}: ${src}" >&2
    return 1
  fi

  mkdir -p "$(dirname "${dst}")"
  rsync -a --delete "${src}/" "${dst}/"
  echo "installed ${label}: ${dst}"
}

mkdir -p "${SKILLS_DIR}"
install_dir "${DEEP_SURVEY_DIR}/codex-skills/literature-downloader" "${SKILLS_DIR}/literature-downloader" "skill literature-downloader"
install_dir "${DEEP_SURVEY_DIR}/codex-skills/chrome-literature-downloader" "${SKILLS_DIR}/chrome-literature-downloader" "skill chrome-literature-downloader"
install_dir "${DEEP_SURVEY_DIR}/codex-skills/paper-broad-reading-analysis" "${SKILLS_DIR}/paper-broad-reading-analysis" "skill paper-broad-reading-analysis"

install_dir "${DEEP_SURVEY_DIR}/workspace-template/plugins/deep-literature-workflow" "${WORKSPACE_PLUGIN_DIR}" "workspace plugin deep-literature-workflow"
install_dir "${DEEP_SURVEY_DIR}/workspace-template/plugins/deep-literature-workflow" "${PLUGIN_CACHE_DIR}" "Codex plugin cache deep-literature-workflow"

echo "Codex Deep Survey dependencies are installed."
