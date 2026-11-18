#!/usr/bin/env bash
set -euo pipefail
umask 022

# Cross-distro bootstrap for kdump-helper
# - Installs minimal prereqs
# - Ensures a modern Python via pyenv (no reliance on distro repos)
# - Creates venv under /opt/kdump-helper/.venv using that Python
# - Installs kdump-helper from GitHub
# - Adds global shim at /usr/local/bin/kdump-helper

REPO_URL="https://github.com/samatild/kdump-helper.git"
INSTALL_ROOT="/opt/kdump-helper"
VENV_DIR="${INSTALL_ROOT}/.venv"
PYENV_ROOT="${INSTALL_ROOT}/pyenv"
# Pick a widely compatible modern Python (OpenSSL compat on older distros)
PYTHON_VERSION="3.11.10"

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
      apt-get install -y git curl ca-certificates patch build-essential \
        libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
        libffi-dev liblzma-dev tk-dev uuid-dev libgdbm-dev libgdbm-compat-dev
      ;;
    dnf)
      dnf install -y git curl ca-certificates patch gcc make \
        openssl-devel bzip2 bzip2-devel libffi-devel zlib-devel \
        readline-devel sqlite-devel xz xz-devel tk-devel gdbm-devel \
        libuuid-devel
      ;;
    yum)
      yum install -y git curl ca-certificates patch gcc make \
        openssl-devel bzip2 bzip2-devel libffi-devel zlib-devel \
        readline-devel sqlite-devel xz xz-devel tk-devel gdbm-devel \
        libuuid-devel
      ;;
    zypper)
      zypper --non-interactive refresh
      zypper --non-interactive install git curl ca-certificates patch gcc make \
        libopenssl-devel zlib-devel libbz2-devel libffi-devel \
        readline-devel sqlite3-devel xz-devel tk-devel gdbm-devel \
        libuuid-devel
      ;;
    *)
      echo "Unsupported distro: install python3, python3-venv, git, curl manually and re-run." >&2
      exit 1
      ;;
  esac
}

install_pyenv() {
  if [[ ! -d "$PYENV_ROOT" ]]; then
    git clone https://github.com/pyenv/pyenv.git "$PYENV_ROOT"
  fi
  export PYENV_ROOT
  export PATH="$PYENV_ROOT/bin:$PATH"
}

install_modern_python() {
  # Ensure pyenv available in PATH
  install_pyenv
  # Build the requested Python if missing
  if [[ ! -x "$PYENV_ROOT/versions/$PYTHON_VERSION/bin/python3" ]]; then
    "${PYENV_ROOT}/bin/pyenv" install -s "$PYTHON_VERSION"
  fi
  PY3_BIN="$PYENV_ROOT/versions/$PYTHON_VERSION/bin/python3"
  echo "Using Python: $($PY3_BIN -V)"
}

create_venv() {
  mkdir -p "$INSTALL_ROOT"
  install_modern_python
  local PY3_BIN="$PYENV_ROOT/versions/$PYTHON_VERSION/bin/python3"
  if [[ ! -d "$VENV_DIR" ]]; then
    "$PY3_BIN" -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  pip install -U pip setuptools wheel
}

install_kdump_helper() {
  pip install --upgrade "git+${REPO_URL}"
  # Also repair existing installs created with a restrictive root umask.
  chmod -R a+rX "$INSTALL_ROOT"
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
