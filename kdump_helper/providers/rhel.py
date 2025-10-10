from __future__ import annotations

import platform
import subprocess
from typing import List

from rich.console import Console

from ..pkg_manager import select_package_manager


def enable_el_debug_repos(kernel_release: str, console: Console) -> None:
    pm = select_package_manager("rhel")
    el8 = ".el8" in kernel_release
    el9 = ".el9" in kernel_release
    cmds: List[List[str]] = []
    # generic
    cmds.append([pm.binary, "config-manager", "--set-enabled", "debuginfo"])
    if el8:
        cmds.extend(
            [
                [
                    "subscription-manager",
                    "repos",
                    "--enable",
                    "rhel-8-for-$(uname -m)-baseos-debug-rpms",
                ],
                [
                    "subscription-manager",
                    "repos",
                    "--enable",
                    "rhel-8-for-$(uname -m)-appstream-debug-rpms",
                ],
            ]
        )
    if el9:
        cmds.extend(
            [
                [
                    "subscription-manager",
                    "repos",
                    "--enable",
                    "rhel-9-for-$(uname -m)-baseos-debug-rpms",
                ],
                [
                    "subscription-manager",
                    "repos",
                    "--enable",
                    "rhel-9-for-$(uname -m)-appstream-debug-rpms",
                ],
            ]
        )
    for c in cmds:
        subprocess.run(c, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def install_el_debuginfo(kernel_release: str, console: Console) -> None:
    pm = select_package_manager("rhel")
    # debuginfo-install first
    subprocess.run(
        [pm.binary, "debuginfo-install", "-y", f"kernel-core-{kernel_release}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # direct installs
    arch = platform.machine() or "x86_64"
    packages: List[str] = [
        f"kernel-debuginfo-{kernel_release}",
        f"kernel-debuginfo-common-{arch}-{kernel_release}",
    ]
    # On SLES/SUSE, flavors differ (default, azure, aws, gcp). Try them too.
    # This function is used for EL-like installs, but we can opportunistically
    # attempt SUSE names when running on SUSE hosts analyzing SUSE kernels.
    for fl in ["default", "azure", "aws", "gcp"]:
        packages.append(f"kernel-{fl}-debuginfo-{kernel_release}")
    for pkg in packages:
        subprocess.run(
            [pm.binary, "install", "-y", pkg],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )


