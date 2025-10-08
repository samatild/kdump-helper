from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

from ..net_utils import download_with_progress


def build_ddebs_base_urls(kernel_release: str) -> list[tuple[str, list[str]]]:
    parts = kernel_release.split("-")
    if len(parts) < 3:
        return []
    base_version = parts[0]
    flavor = parts[2]
    ver_parts = base_version.split(".")
    major_minor = (
        f"{ver_parts[0]}.{ver_parts[1]}" if len(ver_parts) >= 2 else base_version
    )
    urls: list[tuple[str, list[str]]] = []
    # unsigned first
    urls.append(
        (
            f"linux-image-unsigned-{kernel_release}-dbgsym",
            [
                f"http://ddebs.ubuntu.com/ubuntu/pool/main/l/linux-{flavor}-{major_minor}/",
                f"http://ddebs.ubuntu.com/pool/main/l/linux-{flavor}-{major_minor}/",
            ],
        )
    )
    # signed second
    urls.append(
        (
            f"linux-image-{kernel_release}-dbgsym",
            [
                f"http://ddebs.ubuntu.com/ubuntu/pool/main/l/linux-signed-{flavor}-{major_minor}/",
                f"http://ddebs.ubuntu.com/pool/main/l/linux-signed-{flavor}-{major_minor}/",
            ],
        )
    )
    return urls


def find_ddeb_filename(base_url: str, package_prefix: str) -> Optional[str]:
    from urllib.request import urlopen, Request

    try:
        req = Request(base_url, headers={"User-Agent": "kdump-helper/0.1"})
        with urlopen(req) as resp:  # nosec - controlled URL
            html = resp.read().decode("utf-8", "ignore")
    except Exception:
        return None
    matches = re.findall(r'href="([^"\s]+)"', html)
    candidates = [
        m
        for m in matches
        if m.startswith(package_prefix + "_")
        and (m.endswith("_amd64.ddeb") or m.endswith("_amd64.deb"))
    ]
    candidates.sort(key=len, reverse=True)
    return candidates[0] if candidates else None


def download_and_extract_ddeb(
    deb_url: str, deb_path: Path, target_dir: Path, console: Console
) -> bool:
    download_with_progress(deb_url, deb_path, console)
    # Extract the .ddeb/.deb file
    with console.status(f"Extracting {deb_path.name}..."):
        proc = subprocess.run(
            ["bash", "-lc", f"cd {str(target_dir)!s} && dpkg-deb -x {deb_path.name} ."],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                [
                    "bash",
                    "-lc",
                    f"cd {str(target_dir)!s} && ar x {deb_path.name} && tar -xf data.tar.*",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
    return proc.returncode == 0


def locate_vmlinux_paths(target_dir: Path, kernel_release: str) -> list[Path]:
    locations = [
        target_dir
        / "usr"
        / "lib"
        / "debug"
        / "lib"
        / "modules"
        / kernel_release
        / "vmlinux",
        target_dir / "usr" / "lib" / "debug" / "boot" / f"vmlinux-{kernel_release}",
        target_dir / "usr" / "lib" / "debug" / "boot" / f"vmlinux-{kernel_release}.efi",
    ]
    return [p for p in locations if p.exists()]


