# kdump-helper
Prepare any Linux box (RHEL/Ubuntu/Debian/SLES) as a kdump analysis machine.

### Quick start (single-line bootstrap)
```bash
curl -fsSL https://raw.githubusercontent.com/samatild/kdump-helper/main/bootstrap.sh | bash
```

This ensures a modern Python via pyenv (without relying on distro repos), creates an isolated Python env under `/opt/kdump-helper/.venv`, installs `kdump-helper`, and exposes `kdump-helper` on your PATH.

### Manual install (no bootstrap)
If you prefer to install manually or run from a local checkout, use the steps below.

1) Install minimal prerequisites (choose your distro):
```bash
# Ubuntu/Debian (for pyenv build toolchain)
sudo apt-get update && sudo apt-get install -y git curl ca-certificates build-essential \
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libffi-dev \
  liblzma-dev tk-dev uuid-dev libgdbm-dev libgdbm-compat-dev

# RHEL/Rocky/Alma/Fedora (for pyenv build toolchain)
sudo dnf install -y git curl ca-certificates gcc make openssl-devel bzip2 bzip2-devel \
  libffi-devel zlib-devel readline-devel sqlite-devel xz xz-devel tk-devel gdbm-devel libuuid-devel || \
sudo yum install -y git curl ca-certificates gcc make openssl-devel bzip2 bzip2-devel \
  libffi-devel zlib-devel readline-devel sqlite-devel xz xz-devel tk-devel gdbm-devel libuuid-devel

# SLES/openSUSE (for pyenv build toolchain)
sudo zypper --non-interactive refresh && \
sudo zypper --non-interactive install git curl ca-certificates gcc make libopenssl-devel \
  zlib-devel libbz2-devel libffi-devel readline-devel sqlite3-devel xz-devel tk-devel \
  gdbm-devel libuuid-devel
```

2) Install a modern Python with pyenv, then create a venv (absolute path method):
```bash
sudo mkdir -p /opt/kdump-helper && sudo chown "$USER" /opt/kdump-helper
git clone https://github.com/pyenv/pyenv.git /opt/kdump-helper/pyenv
export PYENV_ROOT=/opt/kdump-helper/pyenv
export PATH="$PYENV_ROOT/bin:$PATH"
"$PYENV_ROOT/bin/pyenv" install -s 3.11.10

# Create venv using the absolute pyenv Python path (avoids system python)
PY3="$PYENV_ROOT/versions/3.11.10/bin/python3"
"$PY3" -m venv /opt/kdump-helper/.venv
source /opt/kdump-helper/.venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e .
```

3a) Install from GitHub (recommended):
```bash
python -m pip install "git+https://github.com/samatild/kdump-helper.git"
```

3b) Or install from a local folder (developer mode):
```bash
python -m pip install -e /path/to/kdump-helper
```

4) (Optional) Add a global shim to your PATH:
```bash
sudo ln -sf /opt/kdump-helper/.venv/bin/kdump-helper /usr/local/bin/kdump-helper
```

5) Use it:
```bash
kdump-helper --help
kdump-helper prepare
kdump-helper analyze --vmcore /path/to/vmcore --launch
```

Update to latest:
```bash
# If installed from GitHub
pip install -U "git+https://github.com/samatild/kdump-helper.git"

# If installed in editable mode from a local clone
cd /path/to/kdump-helper && git pull && pip install -e .
```

### Goals
- Install tooling and dependencies for kdump analysis
- Fetch kernel debug symbols automatically (package manager or fallbacks)
- Distro-aware flows for RHEL, Ubuntu, Debian, SLES

### Status
Commands: `prepare`, `validate`, `analyze`.

### Analyze workflow (examples)
```bash
# Install debug symbols by explicit kernel release
kdump-helper analyze --release $(uname -r)

# Or infer from a vmcore and then fetch symbols
kdump-helper analyze --vmcore /path/to/vmcore

# Use a custom target directory and auto-launch crash when ready
kdump-helper analyze --vmcore /path/to/vmcore \
  --target /var/lib/kdump-helper/symbols --launch

# Open with crash once vmlinux is available (if not using --launch)
crash /usr/lib/debug/lib/modules/<release>/vmlinux /path/to/vmcore
```

Manual overrides:
```bash
# Use an already-available vmlinux directly
kdump-helper analyze --vmcore /path/to/vmcore \
  --vmlinux /path/to/vmlinux --launch

# Supply debuginfo RPMs and extract into target (works cross-distro)
kdump-helper analyze --vmcore /path/to/vmcore \
  --kernel-debuginfo ./kernel-debuginfo-<rel>.rpm \
  --kernel-debuginfo ./kernel-debuginfo-common-x86_64-<rel>.rpm \
  --target /var/lib/kdump-helper/symbols --launch
```

Behavior highlights:
- Prefers system package-based install first; then falls back per kernel family:
  - EL7: CentOS 7 debuginfo mirrors
  - EL8: Rocky/Alma rpmfind dynamic mirrors
  - EL9: Rocky mirrors
  - Ubuntu: Canonical ddebs (dynamic filename discovery)
- Skips system package install for Ubuntu guest kernels on non-Ubuntu hosts, and for EL8 kernels on EL9 hosts.
- Prints full download URLs before transfers and shows progress (size, speed, ETA).
```