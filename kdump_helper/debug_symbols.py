
from __future__ import annotations

import re
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from urllib.request import urlopen, Request

from .pkg_manager import PackageManagerError, select_package_manager


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def extract_release_from_vmcore(vmcore_path: Path) -> Optional[str]:
    """Attempt to extract OSRELEASE from a vmcore using makedumpfile.

    Returns kernel release like '5.14.0-362.24.1.el9_3.x86_64' or None.
    """
    if not shutil.which("makedumpfile"):
        return None
    vmcoreinfo = vmcore_path.with_suffix(".vmcoreinfo")
    # makedumpfile -i <out> <vmcore>
    result = _run([
        "makedumpfile",
        "-i",
        str(vmcoreinfo),
        str(vmcore_path),
    ])
    if result.returncode != 0:
        return None
    try:
        content = vmcoreinfo.read_text(errors="ignore")
    except OSError:
        return None
    match = re.search(
        r"^OSRELEASE\s*[:=]\s*(\S+)$",
        content,
        flags=re.MULTILINE,
    )
    if match:
        return match.group(1)
    return None


def extract_release_from_vmcore_via_strings(
    vmcore_path: Path,
) -> Optional[str]:
    """Fallback: scan vmcore strings for OSRELEASE=<rel> or Linux version.
    Returns kernel release string when found, else None.
    """
    if not shutil.which("strings"):
        return None
    # First try OSRELEASE=<rel> which often appears in vmcore strings
    cmd_osrel = (
        "strings -n 8 "
        + str(vmcore_path)
        + " | grep -m1 -E '^OSRELEASE=' | head -n1"
    )
    proc = subprocess.run(
        ["bash", "-lc", cmd_osrel],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout:
        line = proc.stdout.strip().splitlines()[0]
        if line.startswith("OSRELEASE=") and len(line) > 10:
            return line.split("=", 1)[1]

    # Fallback to parsing "Linux version <rel>"
    cmd_linux = (
        "strings -n 8 "
        + str(vmcore_path)
        + " | grep -m1 -E '^Linux version [0-9]' | head -n1"
    )
    proc2 = subprocess.run(
        ["bash", "-lc", cmd_linux],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if proc2.returncode != 0 or not proc2.stdout:
        return None
    line2 = proc2.stdout.strip().splitlines()[0]
    parts = line2.split()
    if len(parts) >= 3 and parts[0] == "Linux" and parts[1] == "version":
        return parts[2]
    return None


def _run_with_progress(
    cmd: list[str], description: str, console: Console
) -> subprocess.CompletedProcess[str]:
    """Run a command with a progress indicator showing real activity."""
    from rich.progress import (
        Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    )
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        progress.add_task(description, total=None)  # Indeterminate progress
        # Start the process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        
        # Keep the spinner going until the process completes
        while process.poll() is None:
            import time
            time.sleep(0.1)
        # Wait for process to complete and get output
        stdout, _ = process.communicate()
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=process.returncode,
            stdout=stdout,
            stderr=""
        )


def install_kernel_debuginfo(
    distro_id: str, kernel_release: str, console: Console
) -> None:
    """Best-effort install of kernel debuginfo/dbgsym for the given release."""
    pm = select_package_manager(distro_id)
    did = distro_id.lower()
    # Enable debug repos where needed; ignore failures.
    if did in {"rhel", "redhat", "centos", "rocky", "almalinux", "fedora"}:
        # Try enabling debuginfo repo (dnf/yum plugin).
        _run_with_progress(
            [pm.binary, "config-manager", "--set-enabled", "debuginfo"],
            "Enabling debuginfo repository...",
            console
        )
        # Best-effort enable common debug repos for EL8/EL9 families
        el8 = ".el8" in kernel_release
        el9 = ".el9" in kernel_release
        enable_cmds: list[list[str]] = []
        if el8:
            enable_cmds.extend([
                [
                    "subscription-manager", "repos", "--enable",
                    "rhel-8-for-$(uname -m)-baseos-debug-rpms"
                ],
                ["subscription-manager", "repos", "--enable", "rhel-8-for-$(uname -m)-appstream-debug-rpms"],
                [pm.binary, "config-manager", "--set-enabled", "baseos-debug-rpms"],
                [pm.binary, "config-manager", "--set-enabled", "appstream-debug-rpms"],
                [pm.binary, "config-manager", "--set-enabled", "baseos-debuginfo"],
                [pm.binary, "config-manager", "--set-enabled", "appstream-debuginfo"],
            ])
        if el9:
            enable_cmds.extend([
                ["subscription-manager", "repos", "--enable", "rhel-9-for-$(uname -m)-baseos-debug-rpms"],
                ["subscription-manager", "repos", "--enable", "rhel-9-for-$(uname -m)-appstream-debug-rpms"],
                [pm.binary, "config-manager", "--set-enabled", "baseos-debug-rpms"],
                [pm.binary, "config-manager", "--set-enabled", "crb-debug-rpms"],
                [pm.binary, "config-manager", "--set-enabled", "baseos-debuginfo"],
                [pm.binary, "config-manager", "--set-enabled", "crb-debuginfo"],
            ])
        for cmd in enable_cmds:
            _run_with_progress(cmd, f"Enabling {' '.join(cmd[-1:])}...", console)
        # Try dnf debuginfo-install first, then package names.
        res = _run_with_progress([
            pm.binary,
            "debuginfo-install",
            "-y",
            f"kernel-core-{kernel_release}",
        ], f"Running debuginfo-install for kernel-core-{kernel_release}...", console)
        
        if res.returncode != 0:
            _run_with_progress([
                pm.binary,
                "install",
                "-y",
                f"kernel-debuginfo-{kernel_release}",
            ], f"Installing kernel-debuginfo-{kernel_release}...", console)
            # Attempt to install the common debuginfo package too (EL8/9)
            arch = platform.machine() or "x86_64"
            _run_with_progress([
                pm.binary,
                "install",
                "-y",
                f"kernel-debuginfo-common-{arch}-{kernel_release}",
            ], f"Installing kernel-debuginfo-common-{arch}-{kernel_release}...", console)
    elif did in {"ubuntu"}:
        # Ensure ddebs is configured is out of scope here; attempt install.
        # Both signed/unsigned flavors may be used.
        _run_with_progress(
            [pm.binary, "update", "-y"],
            "Updating package lists...",
            console
        )  # type: ignore[arg-type]
        res = _run_with_progress([
            pm.binary,
            "install",
            "-y",
            f"linux-image-{kernel_release}-dbgsym",
        ], f"Installing linux-image-{kernel_release}-dbgsym...", console)  # type: ignore[arg-type]
        
        if res.returncode != 0:
            _run_with_progress([
                pm.binary,
                "install",
                "-y",
                f"linux-image-unsigned-{kernel_release}-dbgsym",
            ], "Trying unsigned variant...", console)  # type: ignore[arg-type]
    elif did in {"debian"}:
        _run_with_progress(
            [pm.binary, "update", "-y"],
            "Updating package lists...",
            console
        )  # type: ignore[arg-type]
        _run_with_progress([
            pm.binary,
            "install",
            "-y",
            f"linux-image-{kernel_release}-dbgsym",
        ], f"Installing linux-image-{kernel_release}-dbgsym...", console)  # type: ignore[arg-type]
    elif did in {"sles", "suse", "opensuse-leap", "opensuse-tumbleweed"}:
        _sles_enable_debuginfo_repos(console)
        # Try flavor-specific debuginfo packages based on release suffix
        flavors = ["azure", "aws", "gcp", "default"]
        for fl in flavors:
            pkg = f"kernel-{fl}-debuginfo-{kernel_release}" if fl != "default" else f"kernel-default-debuginfo-{kernel_release}"
            _run_with_progress([
                pm.binary,
                "--non-interactive",
                "install",
                pkg,
            ], f"Installing {pkg}...", console)  # type: ignore[arg-type]
    else:
        raise PackageManagerError(
            "Unsupported distribution for debuginfo install"
        )


def find_vmlinux_paths(kernel_release: str) -> list[Path]:
    """Return likely vmlinux paths for a given release across distros."""
    candidates: list[Path] = []
    # Common locations
    candidates.append(
        Path(
            f"/usr/lib/debug/lib/modules/{kernel_release}/vmlinux"
        )
    )
    candidates.append(
        Path(f"/usr/lib/debug/boot/vmlinux-{kernel_release}")
    )
    candidates.append(
        Path(
            f"/usr/lib/debug/boot/vmlinux-{kernel_release}.debug"
        )
    )
    candidates.append(
        Path(f"/usr/lib/debug/usr/lib/modules/{kernel_release}/vmlinux")
    )
    # Ubuntu specific could be in /usr/lib/debug/ (ddebs layout)
    # Fallback: if /usr/lib/modules/<rel>/build/vmlinux exists
    build_vmlinux = Path(
        f"/usr/lib/modules/{kernel_release}/build/vmlinux"
    )
    if build_vmlinux.exists():
        candidates.append(build_vmlinux)
    return [p for p in candidates if p.exists()]


def check_existing_debug_symbols(kernel_release: str) -> Optional[Path]:
    """Check if debug symbols already exist on the system.
    
    Returns the first valid vmlinux path found, or None if none exist.
    """
    paths = find_vmlinux_paths(kernel_release)
    return paths[0] if paths else None


def find_vmlinux_in_target(target_dir: Path, kernel_release: str) -> list[Path]:
    """Return vmlinux paths within target_dir for a given release if present."""
    base = target_dir / "usr" / "lib" / "debug"
    candidates = [
        base / "lib" / "modules" / kernel_release / "vmlinux",
        base / "boot" / f"vmlinux-{kernel_release}",
        base / "boot" / f"vmlinux-{kernel_release}.debug",
    ]
    return [p for p in candidates if p.exists()]


def check_existing_in_target(target_dir: Path, kernel_release: str) -> Optional[Path]:
    """Return first vmlinux within target_dir if already extracted."""
    found = find_vmlinux_in_target(target_dir, kernel_release)
    return found[0] if found else None


def extract_debuginfo_rpms(
    rpm_files: list[Path],
    target_dir: Path,
    console: Console,
) -> list[Path]:
    """Extract user-supplied kernel debuginfo RPMs into target_dir and return vmlinux paths.

    Accepts one or more RPMs (e.g. kernel-debuginfo and kernel-debuginfo-common).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted_any = False
    for rpm_path in rpm_files:
        if not rpm_path.exists():
            raise PackageManagerError(f"RPM not found: {rpm_path}")
        with console.status(f"Extracting {rpm_path.name}..."):
            proc = subprocess.run(
                [
                    "bash",
                    "-lc",
                    (
                        f"cd {str(target_dir)!s} && rpm2cpio {str(rpm_path)!s} | cpio -idmv"
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if proc.returncode != 0:
            raise PackageManagerError(f"Failed to extract {rpm_path}: {proc.stdout}")
        extracted_any = True

    if not extracted_any:
        return []

    # Try to locate vmlinux under standard extracted locations irrespective of release
    candidates: list[Path] = []
    base = target_dir / "usr" / "lib" / "debug"
    # vmlinux under lib/modules/<rel>/vmlinux (any rel)
    modules_dir = base / "lib" / "modules"
    if modules_dir.exists():
        for rel_dir in modules_dir.iterdir():
            cand = rel_dir / "vmlinux"
            if cand.exists():
                candidates.append(cand)
    # vmlinux under boot
    for p in base.glob("boot/vmlinux-*"):
        candidates.append(p)
    return candidates


def _is_el7_kernel(kernel_release: str) -> bool:
    """Check if this looks like an EL7 (CentOS 7) kernel release."""
    return any(pattern in kernel_release.lower() for pattern in [
        "el7", "centos7", "rhel7", "3.10", "3.11", "3.12", "3.13", "3.14", "3.15", "3.16", "3.17", "3.18", "3.19"
    ])


def _is_el8_kernel(kernel_release: str) -> bool:
    return ".el8" in kernel_release


def _is_el9_kernel(kernel_release: str) -> bool:
    return ".el9" in kernel_release


def _is_ubuntu_kernel(kernel_release: str) -> bool:
    """Check if this looks like an Ubuntu kernel release.
    
    Heuristic: must include Ubuntu-specific flavor tokens and NOT have RHEL-like
    suffixes such as .el7/.el8/.el9.
    """
    lr = kernel_release.lower()
    # If it clearly looks like RHEL/CentOS (el7/el8/el9), it's not Ubuntu
    if re.search(r"(\.el[0-9]|el[0-9](?:[_\.]))", lr):
        return False
    # SLES/SUSE kernels often include a SLE build identifier like '-150700.'
    # e.g. '6.4.0-150700.20.11-azure' → not Ubuntu
    if re.search(r"-\d{6,}\.\d+", lr):
        return False
    ubuntu_tokens = ["ubuntu", "-generic", "-azure", "-aws", "-gcp", "lowlatency"]
    return any(tok in lr for tok in ubuntu_tokens)


def download_ubuntu_debuginfo(
    kernel_release: str,
    target_dir: Path,
    console: Console,
) -> list[Path]:
    """Download Ubuntu debug symbols from Canonical's ddebs repositories.
    
    This handles Ubuntu kernels when running on non-Ubuntu systems.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # If already extracted in target_dir, short-circuit
    pre_existing = find_vmlinux_in_target(target_dir, kernel_release)
    if pre_existing:
        return pre_existing

    # Extract kernel version parts to build repository path(s)
    kernel_parts = kernel_release.split('-')
    if len(kernel_parts) < 3:
        return []

    base_version = kernel_parts[0]   # e.g. 5.15.0
    kernel_type = kernel_parts[2]    # e.g. azure

    # Use major.minor for repo folder, e.g. 5.15
    version_parts = base_version.split('.')
    major_minor = (
        f"{version_parts[0]}.{version_parts[1]}"
        if len(version_parts) >= 2
        else base_version
    )

    # Prefer unsigned package first; then signed variant
    package_candidates: list[tuple[str, str]] = []
    if kernel_type in ["azure", "aws", "gcp"]:
        # unsigned lives in linux-<type>-<major.minor>
        package_candidates.append(
            (
                f"linux-image-unsigned-{kernel_release}-dbgsym",
                f"http://ddebs.ubuntu.com/ubuntu/pool/main/l/linux-{kernel_type}-{major_minor}/",
            )
        )
        # signed lives in linux-signed-<type>-<major.minor>
        package_candidates.append(
            (
                f"linux-image-{kernel_release}-dbgsym",
                f"http://ddebs.ubuntu.com/ubuntu/pool/main/l/linux-signed-{kernel_type}-{major_minor}/",
            )
        )
    else:
        # generic fallback for other flavors
        package_candidates.append(
            (
                f"linux-image-unsigned-{kernel_release}-dbgsym",
                f"http://ddebs.ubuntu.com/ubuntu/pool/main/l/linux-{kernel_type}-{major_minor}/",
            )
        )
        package_candidates.append(
            (
                f"linux-image-{kernel_release}-dbgsym",
                f"http://ddebs.ubuntu.com/ubuntu/pool/main/l/linux-signed-{kernel_type}-{major_minor}/",
            )
        )

    # Helper: list directory entries from ddebs and pick matching file
    def _find_matching_ddeb(base_url: str, package_prefix: str) -> Optional[str]:
        try:
            req = Request(base_url, headers={"User-Agent": "kdump-helper/0.1"})
            with urlopen(req) as resp:  # nosec - controlled URL
                html = resp.read().decode("utf-8", "ignore")
        except Exception:
            return None
        # naive href extraction
        matches = re.findall(r'href="([^"\s]+)"', html)
        # Filter by our package prefix and correct arch/extension
        candidates = [m for m in matches if m.startswith(package_prefix + "_") and m.endswith("_amd64.ddeb")]
        # Prefer the longest (usually full versioned) filename
        candidates.sort(key=len, reverse=True)
        return candidates[0] if candidates else None

    # Try candidates in order
    for pkg_name, base_url in package_candidates:
        console.print(f"[blue]Searching {base_url} for {pkg_name}...[/]")
        deb_filename = _find_matching_ddeb(base_url, pkg_name)
        if not deb_filename:
            continue
        deb_url = f"{base_url}{deb_filename}"
        deb_path = target_dir / deb_filename

        try:
            with console.status(f"Downloading {pkg_name}..."):
                _download_with_progress(deb_url, deb_path, console)

            # Extract the .ddeb/.deb file
            with console.status(f"Extracting {pkg_name}..."):
                proc = subprocess.run([
                    "bash", "-lc",
                    f"cd {str(target_dir)!s} && dpkg-deb -x {deb_path.name} ."
                ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

                if proc.returncode != 0:
                    console.print("[dim]dpkg-deb failed, trying ar extraction...[/]")
                    proc = subprocess.run([
                        "bash", "-lc",
                        f"cd {str(target_dir)!s} && ar x {deb_path.name} && tar -xf data.tar.*"
                    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            if proc.returncode == 0:
                # Look for vmlinux in extracted content
                extracted_paths = [
                    target_dir / "usr" / "lib" / "debug" / "lib" / "modules" / kernel_release / "vmlinux",
                    target_dir / "usr" / "lib" / "debug" / "boot" / f"vmlinux-{kernel_release}",
                    target_dir / "usr" / "lib" / "debug" / "boot" / f"vmlinux-{kernel_release}.efi",
                ]
                found = [p for p in extracted_paths if p.exists()]
                if found:
                    console.print(f"[green]✓ Found vmlinux: {found[0]}[/]")
                    return found
                else:
                    # Debugging info
                    console.print("[dim]Searching for vmlinux in extracted content...[/]")
                    all_files = list(target_dir.rglob("*"))
                    console.print(f"[dim]Total extracted files: {len(all_files)}[/]")
                    if all_files:
                        console.print(f"[dim]Sample files: {[str(f) for f in all_files[:10]]}[/]")
                    vmlinux_files = [f for f in all_files if "vmlinux" in f.name.lower()]
                    if vmlinux_files:
                        console.print(f"[dim]Found vmlinux-like files: {vmlinux_files}[/]")
                        return vmlinux_files
            else:
                console.print(f"[dim]Extraction failed: {proc.stdout[:100]}...[/]")
        except Exception as e:
            console.print(f"[dim]Failed {deb_url}: {str(e)[:60]}...[/]")
            continue

    return []


def download_centos_debuginfo(
    kernel_release: str,
    target_dir: Path,
    console: Console,
) -> list[Path]:
    """Download CentOS 7 kernel-debuginfo RPMs for a given release and extract vmlinux.

    This is a pragmatic fallback for old RHEL7-era kernels where vendor
    debuginfo access may be unavailable. It downloads both 'kernel-debuginfo'
    and 'kernel-debuginfo-common-<arch>' RPMs and extracts them into
    target_dir, then returns any vmlinux paths found.
    """
    # Only attempt CentOS fallback for EL7-era kernels
    if not _is_el7_kernel(kernel_release):
        raise PackageManagerError(
            f"CentOS fallback only works for EL7-era kernels. "
            f"Kernel {kernel_release} appears to be newer. "
            f"Try enabling debug repos or use a different approach."
        )
    
    target_dir.mkdir(parents=True, exist_ok=True)
    # If already extracted in target_dir, short-circuit
    pre_existing = find_vmlinux_in_target(target_dir, kernel_release)
    if pre_existing:
        return pre_existing

    base_url = "http://debuginfo.centos.org/7/x86_64"
    # Discover exact RPM names from directory listing
    try:
        from .providers.centos import find_centos7_debuginfo_rpms
        rpms = find_centos7_debuginfo_rpms(kernel_release)
    except Exception:
        # Fallback to expected names if listing fails
        debuginfo_rpm = f"kernel-debuginfo-{kernel_release}.rpm"
        debuginfo_common_rpm = (
            f"kernel-debuginfo-common-x86_64-{kernel_release}.rpm"
        )
        rpms = [debuginfo_rpm, debuginfo_common_rpm]

    downloaded: list[Path] = []
    for rpm in rpms:
        url = f"{base_url}/{rpm}"
        out_path = target_dir / rpm
        if not out_path.exists():
            console.print(f"[blue]Downloading {out_path.name} from[/] {url}")
            _download_with_progress(url, out_path, console)
        downloaded.append(out_path)

    # Extract both RPMs with one retry on truncated archive
    for rpm_path in downloaded:
        for attempt in range(1, 3):
            with console.status(
                f"Extracting {rpm_path.name} (attempt {attempt})..."
            ):
                proc = subprocess.run(
                    [
                        "bash",
                        "-lc",
                        (
                            f"cd {str(target_dir)!s} && rpm2cpio {rpm_path.name} "
                            "| cpio -idmv"
                        ),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            if proc.returncode == 0:
                break
            if "premature end of file" in (proc.stdout or "") and attempt == 1:
                # Re-download and retry once
                _download_with_progress(
                    f"{base_url}/{rpm_path.name}", rpm_path, console
                )
                continue
            raise PackageManagerError(
                f"Failed to extract {rpm_path}: {proc.stdout}"
            )

    # Look for vmlinux under extracted tree
    extracted_paths = [
        target_dir
        / "usr"
        / "lib"
        / "debug"
        / "lib"
        / "modules"
        / kernel_release
        / "vmlinux",
        target_dir
        / "usr"
        / "lib"
        / "debug"
        / "boot"
        / f"vmlinux-{kernel_release}",
    ]
    return [p for p in extracted_paths if p.exists()]


def download_el8_debuginfo(
    kernel_release: str,
    target_dir: Path,
    console: Console,
) -> list[Path]:
    """Download EL8 kernel debuginfo RPMs from public mirrors and extract vmlinux."""
    target_dir.mkdir(parents=True, exist_ok=True)
    pre_existing = find_vmlinux_in_target(target_dir, kernel_release)
    if pre_existing:
        return pre_existing

    try:
        from .providers.el8 import find_el8_debuginfo_rpms
        rpm_urls = find_el8_debuginfo_rpms(kernel_release)
    except Exception:
        rpm_urls = []
    if not rpm_urls:
        raise PackageManagerError("EL8 debuginfo not found in known mirrors")

    downloaded: list[Path] = []
    for url in rpm_urls:
        out_path = target_dir / url.rsplit("/", 1)[-1]
        if not out_path.exists():
            console.print(f"[blue]Downloading {out_path.name} from[/] {url}")
            _download_with_progress(url, out_path, console)
        downloaded.append(out_path)

    # Extract
    for rpm_path in downloaded:
        with console.status(f"Extracting {rpm_path.name}..."):
            proc = subprocess.run(
                [
                    "bash",
                    "-lc",
                    (
                        f"cd {str(target_dir)!s} && rpm2cpio {rpm_path.name} | cpio -idmv"
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if proc.returncode != 0:
            raise PackageManagerError(f"Failed to extract {rpm_path}: {proc.stdout}")

    extracted_paths = [
        target_dir / "usr" / "lib" / "debug" / "lib" / "modules" / kernel_release / "vmlinux",
        target_dir / "usr" / "lib" / "debug" / "boot" / f"vmlinux-{kernel_release}",
    ]
    return [p for p in extracted_paths if p.exists()]


def download_el9_debuginfo(
    kernel_release: str,
    target_dir: Path,
    console: Console,
) -> list[Path]:
    """Download EL9 kernel debuginfo RPMs from Rocky mirrors and extract vmlinux."""
    target_dir.mkdir(parents=True, exist_ok=True)
    pre_existing = find_vmlinux_in_target(target_dir, kernel_release)
    if pre_existing:
        return pre_existing

    try:
        from .providers.el9 import find_el9_debuginfo_rpms
        rpm_urls = find_el9_debuginfo_rpms(kernel_release)
    except Exception:
        rpm_urls = []
    if not rpm_urls:
        raise PackageManagerError("EL9 debuginfo not found in known mirrors")

    downloaded: list[Path] = []
    for url in rpm_urls:
        out_path = target_dir / url.rsplit("/", 1)[-1]
        if not out_path.exists():
            console.print(f"[blue]Re-downloading {out_path.name} from[/] {url}")
            _download_with_progress(url, out_path, console)
        downloaded.append(out_path)

    for rpm_path in downloaded:
        with console.status(f"Extracting {rpm_path.name}..."):
            proc = subprocess.run(
                [
                    "bash",
                    "-lc",
                    (
                        f"cd {str(target_dir)!s} && rpm2cpio {rpm_path.name} | cpio -idmv"
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if proc.returncode != 0:
            raise PackageManagerError(f"Failed to extract {rpm_path}: {proc.stdout}")

    extracted_paths = [
        target_dir / "usr" / "lib" / "debug" / "lib" / "modules" / kernel_release / "vmlinux",
        target_dir / "usr" / "lib" / "debug" / "boot" / f"vmlinux-{kernel_release}",
    ]
    return [p for p in extracted_paths if p.exists()]


def launch_crash(vmlinux_path: Path, vmcore_path: Path, console: Console) -> None:
    """Launch crash with the provided vmlinux and vmcore paths."""
    crash_bin = shutil.which("crash")
    if not crash_bin:
        # Check common custom install locations
        candidates = [
            Path("/usr/local/bin/crash"),
            Path.home() / ".local" / "bin" / "crash",
        ]
        for p in candidates:
            if p.exists():
                crash_bin = str(p)
                break
    if not crash_bin:
        raise PackageManagerError(
            "crash command not found. If built from source, ensure /usr/local/bin or ~/.local/bin is on PATH."
        )

    cmd = [crash_bin, str(vmlinux_path), str(vmcore_path)]
    console.print(f"[green]Launching crash: {' '.join(cmd)}[/]")
    subprocess.run(cmd, check=False)


def _download_with_progress(
    url: str,
    out_path: Path,
    console: Console,
) -> None:
    max_retries = 3
    last_err: Optional[str] = None
    for attempt in range(1, max_retries + 1):
        req = Request(url, headers={"User-Agent": "kdump-helper/0.1"})
        try:
            with urlopen(req) as resp:  # nosec - controlled URL
                total_str = resp.getheader("Content-Length")
                total = (
                    int(total_str) if total_str and total_str.isdigit() else 0
                )
                columns = [
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    TimeRemainingColumn(),
                ]
                with Progress(*columns, console=console) as progress:
                    task_id = progress.add_task(
                        f"Downloading {out_path.name}", total=total or None
                    )
                    bytes_written = 0
                    with open(out_path, "wb") as outf:
                        while True:
                            chunk = resp.read(1024 * 64)
                            if not chunk:
                                break
                            outf.write(chunk)
                            bytes_written += len(chunk)
                            progress.update(task_id, advance=len(chunk))
                if total and out_path.stat().st_size != total:
                    last_err = (
                        f"size mismatch: expected {total} got "
                        f"{out_path.stat().st_size}"
                    )
                    continue
                return
        except Exception as e:
            last_err = str(e)
    raise PackageManagerError(f"Failed to download {url}: {last_err}")


def _sles_enable_debuginfo_repos(console: Console) -> None:
    """Enable SLES debuginfo repos by parsing zypper repos and turning on matching aliases.

    Looks for repos with names containing 'Debuginfo' and enables them via
    `zypper modifyrepo --enable <alias-or-number>`.
    """
    # List repos with numbers
    proc = subprocess.run(
        ["bash", "-lc", "zypper repos"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return
    lines = proc.stdout.splitlines()
    # Collect numeric ids for debuginfo repos
    ids_to_enable: list[str] = []
    for line in lines:
        # Expect lines like: ' 1 | Alias | Name-with-Debuginfo | ...'
        if "Debuginfo" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if not parts:
            continue
        id_field = parts[0].strip()
        if id_field.isdigit():
            ids_to_enable.append(id_field)
    # Enable found repos
    for rid in ids_to_enable:
        _run_with_progress(
            ["zypper", "--non-interactive", "modifyrepo", "--enable", rid],
            f"Enabling debuginfo repo {rid}...",
            console,
        )

