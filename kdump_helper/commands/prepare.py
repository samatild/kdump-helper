from typing import List
import subprocess
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ..distro import detect_distro
from ..pkg_manager import select_package_manager


console = Console()


def _packages_for_distro(distro_id: str) -> List[str]:
    did = distro_id.lower()
    # Minimal, to be expanded per-distro
    if did in {"ubuntu", "debian"}:
        return [
            "kdump-tools",
            "kexec-tools",
            "makedumpfile",
            "cpio",
            "rpm",
        ]
    if did in {"rhel", "redhat", "centos", "rocky", "almalinux", "fedora"}:
        # On RHEL-like distros, makedumpfile is provided by kexec-tools
        # rpm2cpio is provided by rpm-build
        return ["kexec-tools", "cpio", "rpm-build"]
    if did in {"sles", "suse", "opensuse-leap", "opensuse-tumbleweed"}:
        return ["kexec-tools", "makedumpfile", "cpio"]
    return ["kexec-tools", "makedumpfile", "cpio"]


def prepare() -> None:
    """Prepare this machine for kdump analysis.

    Installs core tools (kexec/crash/makedumpfile/gdb and helpers) using the
    appropriate package manager for the detected distro.
    """
    info = detect_distro()
    pm = select_package_manager(info.id)
    pkgs = _packages_for_distro(info.id)
    console.print(
        Panel.fit(
            f"Installing baseline packages on "
            f"[bold]{info.pretty_name or info.id}[/]"
        )
    )
    pm.update_metadata()
    pm.install(pkgs)
    # Build from source on most distros; on SLES/SUSE, use system crash
    if info.id.lower() in {"sles", "suse", "opensuse-leap", "opensuse-tumbleweed"}:
        console.print(Panel.fit("SUSE detected; installing distro crash instead of building"))
        try:
            pm.install(["crash", "gdb"])  # best-effort; gdb optional
        except Exception:
            pm.install(["crash"])  # fallback if gdb not available
    else:
        # Build gdb/crash from source to ensure latest features on non-SUSE
        console.print(Panel.fit("Installing build prerequisites..."))
        _ensure_build_deps(info.id, pm)
        console.print(Panel.fit("Building crash (LZO) from source..."))
        _build_crash_from_source(pm)

    console.print("[green]Done.[/]")


def _run_with_progress(cmd: List[str], description: str) -> subprocess.CompletedProcess:
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        progress.add_task(description, total=None)
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        return proc



def _build_crash_from_source(pm) -> None:
    build_root = Path("/var/lib/kdump-helper/build")
    build_root.mkdir(parents=True, exist_ok=True)
    src_dir = build_root / "crash"

    if src_dir.exists():
        _run_with_progress(["bash", "-lc", f"cd {src_dir} && git reset --hard && git clean -fdx"], "Cleaning previous crash tree...")
    else:
        _run_with_progress(["git", "clone", "https://github.com/crash-utility/crash.git", str(src_dir)], "Cloning crash sources...")

    proc = _run_with_progress(["bash", "-lc", f"cd {src_dir} && make clean"], "Cleaning...")
    if proc.returncode != 0:
        raise RuntimeError(f"crash make clean failed:\n{proc.stdout}")
    # Detect GDB tarball that crash will fetch by dry-running the unzip step
    proc_dry = _run_with_progress([
        "bash", "-lc", f"cd {src_dir} && make -n gdb_unzip || true"
    ], "Detecting GDB tarball...")
    gdb_tarball = None
    if proc_dry.stdout:
        import re as _re
        m = _re.search(r"gdb-(\d+\.\d+)\.tar\.gz", proc_dry.stdout)
        if m:
            gdb_tarball = f"gdb-{m.group(1)}.tar.gz"

    # If determined, pre-download with our progress UI into crash dir
    if gdb_tarball:
        dest_tar = Path(src_dir) / gdb_tarball
        if not dest_tar.exists() or dest_tar.stat().st_size == 0:
            from ..net_utils import download_with_progress
            # Prefer mirror first, fallback to upstream if needed
            mirror_url = f"https://mirror.dogado.de/gnu/gdb/{gdb_tarball}"
            upstream_url = f"https://ftp.gnu.org/gnu/gdb/{gdb_tarball}"
            try:
                download_with_progress(mirror_url, dest_tar, console)
            except Exception:
                download_with_progress(upstream_url, dest_tar, console)

    # Ensure wget exists; crash Makefile may still fall back to its own download
    pm.install(["wget"])  # best-effort across distros
    proc = _run_with_progress([
        "bash", "-lc",
        f"cd {src_dir} && make -j$(nproc) lzo"
    ], "Building crash (lzo)...")
    if proc.returncode != 0:
        raise RuntimeError(f"crash build failed:\n{proc.stdout}")

    install_dir = "/usr/local/bin"
    target_path = Path(install_dir) / "crash"
    if not os.access(install_dir, os.W_OK):
        # Fallback to user-local bin if not writable
        install_dir = str(Path.home() / ".local" / "bin")
        target_path = Path(install_dir) / "crash"
        Path(install_dir).mkdir(parents=True, exist_ok=True)
        console.print(f"[yellow]Install dir not writable; installing to {install_dir}[/]")

    proc = _run_with_progress(
        [
            "bash",
            "-lc",
            f"cd {src_dir} && install -D -m 0755 crash {target_path}",
        ],
        f"Installing crash to {target_path}...",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"crash install failed:\n{proc.stdout}")
    if not target_path.exists():
        raise RuntimeError(f"crash not found at {target_path} after install")


def _ensure_build_deps(distro_id: str, pm) -> None:
    did = distro_id.lower()
    if did in {"ubuntu", "debian"}:
        pkgs = [
            "build-essential",
            "git",
            "libncurses-dev",
            "libreadline-dev",
            "python3-dev",
            "texinfo",
            "bison",
            "flex",
            "libgmp-dev",
            "libmpfr-dev",
            "libmpc-dev",
            "zlib1g-dev",
            "liblzo2-dev",
            
            "xz-utils",
            "curl",
            "pkg-config",
            "autoconf",
            "automake",
            "libtool",
        ]
        pm.install(pkgs)
    elif did in {"rhel", "redhat", "centos", "rocky", "almalinux", "fedora"}:
        # Try to install development tools group if available
        _run_with_progress(["bash", "-lc", "(dnf -y groupinstall 'Development Tools' || yum -y groupinstall 'Development Tools') >/dev/null 2>&1 || true"], "Ensuring Development Tools group...")
        pkgs = [
            "git",
            "gcc",
            "gcc-c++",
            "make",
            "ncurses-devel",
            "readline-devel",
            "python3-devel",
            "texinfo",
            "bison",
            "flex",
            "gmp-devel",
            "mpfr-devel",
            "libmpc-devel",
            "zlib-devel",
            "lzo-devel",
            
            "xz",
            "curl",
            "pkgconf-pkg-config",
            "autoconf",
            "automake",
            "libtool",
        ]
        pm.install(pkgs)
    elif did in {"sles", "suse", "opensuse-leap", "opensuse-tumbleweed"}:
        pkgs = [
            "gcc",
            "gcc-c++",
            "make",
            "git",
            "ncurses-devel",
            "readline-devel",
            "python3-devel",
            "texinfo",
            "bison",
            "flex",
            "gmp-devel",
            "mpfr-devel",
            "mpc-devel",
            "zlib-devel",
            "lzo-devel",
            
            "xz",
            "curl",
            "pkg-config",
            "autoconf",
            "automake",
            "libtool",
        ]
        pm.install(pkgs)


def _fetch_gdb_tarball() -> Path:
    from urllib.request import urlopen, Request
    import re as _re

    build_root = Path("/var/lib/kdump-helper/build")
    build_root.mkdir(parents=True, exist_ok=True)
    gdb_dir = build_root / "gdb"
    gdb_dir.mkdir(parents=True, exist_ok=True)

    # Discover latest stable gdb tarball
    index_urls = [
        "https://ftp.gnu.org/gnu/gdb/",
        "http://ftp.gnu.org/gnu/gdb/",
    ]
    tar_name = None
    for idx in index_urls:
        try:
            req = Request(idx, headers={"User-Agent": "kdump-helper/0.1"})
            with urlopen(req) as resp:
                html = resp.read().decode("utf-8", "ignore")
            # Prefer .tar.gz because crash Makefile unpacks .tar.gz by default
            candidates = _re.findall(r"gdb-(\d+\.\d+)\.tar\.gz", html)
            if candidates:
                # pick highest version
                def _ver_tuple(s: str):
                    a, b = s.split(".")
                    return (int(a), int(b))

                latest = sorted(candidates, key=_ver_tuple)[-1]
                tar_name = f"gdb-{latest}.tar.gz"
                base = idx
                break
        except Exception:
            continue
    if not tar_name:
        # fallback to a known recent version
        tar_name = "gdb-14.2.tar.gz"
        base = "https://ftp.gnu.org/gnu/gdb/"

    from ..net_utils import download_with_progress

    tar_url = f"{base}{tar_name}"
    tar_path = gdb_dir / tar_name
    if tar_path.exists() and tar_path.stat().st_size > 0:
        console.print(f"[blue]Using cached GDB tarball: {tar_path}[/]")
    else:
        download_with_progress(tar_url, tar_path, console)
    return tar_path


