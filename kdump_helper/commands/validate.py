import os
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel


console = Console()


def validate_command() -> None:
    """Validate environment readiness for kdump analysis."""
    console.print(Panel.fit("Validating kdump analysis environment"))

    # Binaries required for baseline operations
    crash_in_path = shutil.which("crash")
    # Also check common custom install locations used by prepare
    custom_crash_candidates = [
        Path("/usr/local/bin/crash"),
        Path.home() / ".local" / "bin" / "crash",
    ]
    crash_path = crash_in_path
    if not crash_path:
        for p in custom_crash_candidates:
            if p.exists():
                crash_path = str(p)
                break

    checks = {
        "kexec": shutil.which("kexec"),
        "crash": crash_path,
        "makedumpfile": shutil.which("makedumpfile"),
        "strings": shutil.which("strings"),
        # Symbol extraction helpers
        "ar": shutil.which("ar"),
        "dpkg-deb (optional)": shutil.which("dpkg-deb"),
        "rpm2cpio (EL7 fallback)": shutil.which("rpm2cpio"),
        "cpio": shutil.which("cpio"),
        "tar": shutil.which("tar"),
        "xz": shutil.which("xz"),
        "wget": shutil.which("wget"),
        "curl": shutil.which("curl"),
    }
    for name, path in checks.items():
        console.print(f"{name}: {'yes' if path else 'no'}{f' ({path})' if path else ''}")

    # Crash version (best-effort)
    if crash_path:
        # If not in PATH but found in a custom location, hint to add to PATH
        if not crash_in_path:
            console.print(
                f"[yellow]Note:[/] crash found at {crash_path} but not on PATH. "
                f"Consider adding {str(Path(crash_path).parent)} to PATH."
            )
        proc = subprocess.run([crash_path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line = (proc.stdout or "").splitlines()[0] if proc.stdout else ""
        if line:
            console.print(f"crash version: {line}")

    # Writable directories used by kdump-helper
    dirs = [
        Path("/var/lib/kdump-helper/symbols"),
        Path("/var/lib/kdump-helper/build"),
    ]
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            writable = os.access(d, os.W_OK)
            console.print(f"{str(d)}: exists, writable={str(writable).lower()}")
        except Exception as e:
            console.print(f"{str(d)}: error creating: {e}")

    # kdump service status intentionally omitted; not required for analysis


