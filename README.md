# kdump-helper
Prepare any Linux box (RHEL/Ubuntu/Debian/SLES) as a kdump analysis machine.

### Quick start (single-line bootstrap)
```bash
curl -fsSL https://raw.githubusercontent.com/samatild/kdump-helper/main/bootstrap.sh | bash
```

This installs minimal prerequisites, creates an isolated Python env under `/opt/kdump-helper/.venv`, installs `kdump-helper`, and exposes `kdump-helper` on your PATH.

### Manual install (no bootstrap)
If you prefer to install manually or run from a local checkout, use the steps below.

1) Install minimal prerequisites (choose your distro):
```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y python3 python3-venv git curl ca-certificates

# RHEL/Rocky/Alma/Fedora
sudo dnf install -y python3 python3-virtualenv git curl ca-certificates || \
sudo yum install -y python3 python3-virtualenv git curl ca-certificates

# SLES/openSUSE
sudo zypper --non-interactive refresh && \
sudo zypper --non-interactive install python3 python3-virtualenv git curl ca-certificates
```

2) Create a dedicated virtual environment and activate it:
```bash
sudo mkdir -p /opt/kdump-helper && sudo chown "$USER" /opt/kdump-helper
python3 -m venv /opt/kdump-helper/.venv
source /opt/kdump-helper/.venv/bin/activate
pip install -U pip setuptools wheel
```

3a) Install from GitHub (recommended):
```bash
pip install "git+https://github.com/samatild/kdump-helper.git"
```

3b) Or install from a local folder (developer mode):
```bash
pip install -e /path/to/kdump-helper
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