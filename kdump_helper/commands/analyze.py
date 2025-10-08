from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
import typer

from ..distro import detect_distro
from ..debug_symbols import (
    extract_release_from_vmcore,
    extract_release_from_vmcore_via_strings,
    install_kernel_debuginfo,
    find_vmlinux_paths,
    download_centos_debuginfo,
    download_ubuntu_debuginfo,
    check_existing_debug_symbols,
    launch_crash,
)
from ..pkg_manager import PackageManagerError


console = Console()


def analyze(
    release: Optional[str] = typer.Option(
        None,
        "--release",
        help="Guest kernel release (uname -r) to fetch symbols for",
    ),
    vmcore: Optional[Path] = typer.Option(
        None,
        "--vmcore",
        help="Path to vmcore to infer kernel release if --release is omitted",
    ),
    target: Path = typer.Option(
        Path("/var/lib/kdump-helper/symbols"),
        "--target",
        help="Directory to store downloaded/extracted debug symbols",
    ),
    launch: bool = typer.Option(
        False,
        "--launch",
        help="Launch crash automatically after symbols are ready (requires --vmcore)",
    ),
    vmlinux: Optional[Path] = typer.Option(
        None,
        "--vmlinux",
        help="Path to a vmlinux to use directly (skips downloads)",
    ),
    kernel_debuginfo: Optional[list[Path]] = typer.Option(
        None,
        "--kernel-debuginfo",
        help="One or more kernel-debuginfo RPMs to extract into --target",
    ),
) -> None:
    """Analyze a vmcore by preparing required kernel debug symbols.

    - If --vmcore is provided and --release is omitted, attempts to infer the
      kernel release from the dump.
    - Skips downloads if symbols already exist on the system or in --target.
    - Falls back to CentOS debuginfo RPMs for older EL7-era kernels.
    """
    info = detect_distro()
    rel = release
    if rel is None and vmcore is not None:
        console.print("Inferring kernel release from vmcore...")
        rel = extract_release_from_vmcore(vmcore)
    if rel is None and vmcore is not None:
        console.print(
            "makedumpfile did not provide OSRELEASE, trying strings fallback..."
        )
        rel = extract_release_from_vmcore_via_strings(vmcore)
    if rel is None:
        raise typer.BadParameter(
            "Could not determine kernel release. Provide --release explicitly, "
            "or ensure makedumpfile/strings are available."
        )

    # Manual overrides first
    if vmlinux is not None:
        if not vmlinux.exists():
            raise typer.BadParameter(f"vmlinux not found: {vmlinux}")
        console.print(f"[green]✓ Using provided vmlinux: {vmlinux}[/]")
        vmlinux_path = vmlinux
        if launch and vmcore is not None:
            launch_crash(vmlinux_path, vmcore, console)
        return

    if kernel_debuginfo:
        from ..debug_symbols import extract_debuginfo_rpms
        console.print("[blue]Extracting user-supplied debuginfo RPMs...[/]")
        extracted = extract_debuginfo_rpms(kernel_debuginfo, target, console)
        if extracted:
            console.print("[green]✓ Extracted vmlinux paths:[/]")
            for p in extracted:
                console.print(f"  - {p}")
            vmlinux_path = extracted[0]
            if launch and vmcore is not None:
                launch_crash(vmlinux_path, vmcore, console)
            return
        else:
            console.print("[yellow]✗ RPM extraction did not yield vmlinux; continuing...[/]")

    # Decide kernel family to drive strategy
    from ..debug_symbols import _is_el7_kernel, _is_el8_kernel, _is_el9_kernel, _is_ubuntu_kernel
    is_el7 = _is_el7_kernel(rel)
    is_el8 = _is_el8_kernel(rel)
    is_el9 = _is_el9_kernel(rel)
    is_ubuntu = _is_ubuntu_kernel(rel)

    # FIRST: Check if debug symbols already exist before any downloads
    console.print(f"[blue]Checking for existing debug symbols for {rel}...[/]")
    existing_vmlinux = check_existing_debug_symbols(rel)
    if existing_vmlinux:
        console.print(
            f"[green]✓ Found existing debug symbols: {existing_vmlinux}[/]"
        )
        vmlinux_path = existing_vmlinux
    else:
        console.print("[yellow]✗ No existing debug symbols found on system[/]")
        
        # Check if already extracted in target directory
        console.print(f"[blue]Checking target directory {target}...[/]")
        from ..debug_symbols import check_existing_in_target
        target_vmlinux = check_existing_in_target(target, rel)
        if target_vmlinux:
            console.print(f"[green]✓ Found extracted symbols in target: {target_vmlinux}[/]")
            vmlinux_path = target_vmlinux
        else:
            console.print("[yellow]✗ No symbols found in target directory[/]")
            
            # Strategy selection: avoid useless steps
            attempted_pkg_install = False
            if is_ubuntu and info.id not in {"ubuntu", "debian"}:
                # Ubuntu guest kernel on non-Ubuntu host: skip system package manager
                console.print(
                    Panel.fit(
                        "Ubuntu kernel detected; skipping system package manager on this host"
                    )
                )
            else:
                console.print(
                    Panel.fit(
                        f"Attempting package-based install for [bold]{rel}[/] on "
                        f"[bold]{info.id}[/]"
                    )
                )
                # Skip package install if host is EL9+ and guest kernel is EL8
                skip_pkg = (info.id in {"rhel", "redhat", "rocky", "almalinux", "centos"}) and is_el8 and (info.version_id or "").startswith("9")
                if skip_pkg:
                    console.print("[yellow]Skipping system package install on EL9 host for EL8 kernel[/]")
                else:
                    try:
                        console.print("[blue]Installing kernel debuginfo packages...[/]")
                        install_kernel_debuginfo(info.id, rel, console)
                        attempted_pkg_install = True
                    except PackageManagerError as e:
                        console.print(f"[yellow]✗ Package-based install failed: {e}[/]")
                        console.print("[blue]Checking for any installed symbols...[/]")
            
            paths = find_vmlinux_paths(rel)
            if paths:
                console.print("[green]✓ Package-based install yielded vmlinux:[/]")
                for p in paths:
                    console.print(f"  - {p}")
                vmlinux_path = paths[0]
            else:
                if attempted_pkg_install:
                    console.print("[yellow]✗ Package install did not yield vmlinux[/]")

                # Kernel-family driven fallbacks
                if is_el7:
                    console.print(
                        Panel.fit("Attempting CentOS debuginfo fallback download...")
                    )
                    try:
                        extracted = download_centos_debuginfo(rel, target, console)
                        if extracted:
                            console.print("[green]✓ CentOS fallback successful:[/]")
                            for p in extracted:
                                console.print(f"  - {p}")
                            vmlinux_path = extracted[0]
                        else:
                            console.print("[red]✗ CentOS fallback did not yield vmlinux[/]")
                            return
                    except PackageManagerError as e:
                        console.print(f"[yellow]✗ CentOS fallback failed: {e}[/]")
                        return
                elif is_el8:
                    console.print(
                        Panel.fit("Attempting EL8 debuginfo fallback download from mirrors...")
                    )
                    from ..debug_symbols import download_el8_debuginfo
                    try:
                        extracted = download_el8_debuginfo(rel, target, console)
                        if extracted:
                            console.print("[green]✓ EL8 fallback successful:[/]")
                            for p in extracted:
                                console.print(f"  - {p}")
                            vmlinux_path = extracted[0]
                        else:
                            console.print("[red]✗ EL8 fallback did not yield vmlinux[/]")
                            return
                    except PackageManagerError as e:
                        console.print(f"[yellow]✗ EL8 fallback failed: {e}[/]")
                        return
                elif is_el9:
                    console.print(
                        Panel.fit("Attempting EL9 debuginfo fallback download from mirrors...")
                    )
                    from ..debug_symbols import download_el9_debuginfo
                    try:
                        extracted = download_el9_debuginfo(rel, target, console)
                        if extracted:
                            console.print("[green]✓ EL9 fallback successful:[/]")
                            for p in extracted:
                                console.print(f"  - {p}")
                            vmlinux_path = extracted[0]
                        else:
                            console.print("[red]✗ EL9 fallback did not yield vmlinux[/]")
                            return
                    except PackageManagerError as e:
                        console.print(f"[yellow]✗ EL9 fallback failed: {e}[/]")
                        return
                elif is_ubuntu:
                    console.print(
                        Panel.fit("Attempting Ubuntu debuginfo fallback download...")
                    )
                    extracted = download_ubuntu_debuginfo(rel, target, console)
                    if extracted:
                        console.print("[green]✓ Ubuntu fallback successful:[/]")
                        for p in extracted:
                            console.print(f"  - {p}")
                        vmlinux_path = extracted[0]
                    else:
                        console.print("[red]✗ Ubuntu fallback did not yield vmlinux[/]")
                        console.print(
                            "[red]✗ All methods failed. For Ubuntu kernels, try:[/]"
                        )
                        console.print(
                            "  1. Enable ddebs: sudo apt-get install ubuntu-dbgsym-keyring"
                        )
                        console.print(
                            f"  2. Install manually: sudo apt-get install linux-image-{rel}-dbgsym"
                        )
                        console.print("  3. Or provide vmlinux manually")
                        return
                else:
                    console.print(
                        f"[yellow]✗ No known fallback for kernel family of {rel}."
                    )
                    console.print(
                        "[red]✗ All methods failed. Try manual installation or provide vmlinux manually.[/]"
                    )
                    return

    # Launch crash if requested and vmcore provided
    if launch and vmcore is not None:
        launch_crash(vmlinux_path, vmcore, console)


