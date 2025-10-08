#!/usr/bin/env bash
set -euo pipefail

# Cross-distro bootstrap for kdump-helper
# - Installs minimal prereqs
# - Creates venv under /opt/kdump-helper/.venv
# - Installs kdump-helper from GitHub
# - Adds a global shim at /usr/local/bin/kdump-helper

REPO_URL="https://github.com/samatild/kdump-helper.git"
INSTALL_ROOT="/opt/kdump-helper"
VENV_DIR="${INSTALL_ROOT}/.venv"

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (or with sudo)." >&2
    exit 1
  fi
}

detect_distro() {
  if command -v apt-get >/dev/null 2>&1; then echo deb; return; fi
  if command -v dnf >/dev/null 2>&1; then echo dnf; return; fi
  if command -v yum >/dev/null 2>&1; then echo yum; return; fi
  if command -v zypper >/dev/null 2>&1; then echo zypper; return; fi
  echo unknown
}

install_prereqs() {
  local pm=$1
  case "$pm" in
    deb)
      apt-get update -y
      apt-get install -y python3 python3-venv git curl ca-certificates
      ;;
    dnf)
      dnf install -y python3 python3-virtualenv git curl ca-certificates
      ;;
    yum)
      yum install -y python3 python3-virtualenv git curl ca-certificates || true
      ;;
    zypper)
      zypper --non-interactive refresh
      zypper --non-interactive install python3 python3-virtualenv git curl ca-certificates
      ;;
    *)
      echo "Unsupported distro: install python3, python3-venv, git, curl manually and re-run." >&2
      exit 1
      ;;
  esac
}

create_venv() {
  mkdir -p "$INSTALL_ROOT"
  if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  pip install -U pip setuptools wheel
}

install_kdump_helper() {
  pip install "git+${REPO_URL}"
  ln -sf "$VENV_DIR/bin/kdump-helper" /usr/local/bin/kdump-helper
}

main() {
  require_root
  pm=$(detect_distro)
  install_prereqs "$pm"
  create_venv
  install_kdump_helper
  echo "kdump-helper installed. Try: kdump-helper --help"
}

main "$@"


