from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Sequence


class PackageManagerError(RuntimeError):
    pass


def run_cmd(cmd: Sequence[str]) -> None:
    process = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.returncode != 0:
        message = (
            f"Command failed ({process.returncode}): {' '.join(cmd)}\n"
            f"{process.stdout}"
        )
        raise PackageManagerError(message)


@dataclass
class PackageManager:
    binary: str

    def install(self, packages: List[str]) -> None:
        raise NotImplementedError

    def update_metadata(self) -> None:
        raise NotImplementedError


class AptManager(PackageManager):
    def __init__(self) -> None:
        super().__init__(binary="apt-get")

    def update_metadata(self) -> None:
        run_cmd([self.binary, "update", "-y"])

    def install(self, packages: List[str]) -> None:
        run_cmd([self.binary, "install", "-y", *packages])


class DnfManager(PackageManager):
    def __init__(self) -> None:
        super().__init__(binary="dnf" if shutil.which("dnf") else "yum")

    def update_metadata(self) -> None:
        run_cmd([self.binary, "makecache", "-y"])

    def install(self, packages: List[str]) -> None:
        run_cmd([self.binary, "install", "-y", *packages])


class ZypperManager(PackageManager):
    def __init__(self) -> None:
        super().__init__(binary="zypper")

    def update_metadata(self) -> None:
        run_cmd([self.binary, "--non-interactive", "refresh"])

    def install(self, packages: List[str]) -> None:
        run_cmd([self.binary, "--non-interactive", "install", *packages])


def select_package_manager(distro_id: str) -> PackageManager:
    did = distro_id.lower()
    if did in {"ubuntu", "debian"}:
        return AptManager()
    if did in {"rhel", "redhat", "centos", "rocky", "almalinux", "fedora", "azurelinux"}:
        return DnfManager()
    if did in {"sles", "suse", "opensuse-leap", "opensuse-tumbleweed"}:
        return ZypperManager()
    # Fallback heuristics by available binary
    if shutil.which("apt-get"):
        return AptManager()
    if shutil.which("dnf") or shutil.which("yum"):
        return DnfManager()
    if shutil.which("zypper"):
        return ZypperManager()
    raise PackageManagerError("Unsupported distribution: no known package manager found")
