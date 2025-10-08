from __future__ import annotations

import re


# Alma no longer provides debug packages; use Rocky devel debug tree only.


def _list_dir(url: str) -> list[str]:
    from urllib.request import urlopen, Request

    req = Request(url, headers={"User-Agent": "kdump-helper/0.1"})
    with urlopen(req) as resp:  # nosec - controlled URL
        html = resp.read().decode("utf-8", "ignore")
    return re.findall(r'href="([^"\s]+)"', html)


def _el8_minor_path(kernel_release: str) -> str:
    """Return minor path like '8.10' from a release ending in .el8_10."""
    m = re.search(r"\.el8_(\d+)", kernel_release)
    if m:
        return f"8.{m.group(1)}"
    return "8"


def _candidate_bases(kernel_release: str) -> list[str]:
    minor = _el8_minor_path(kernel_release)
    # Prefer AlmaLinux via rpmfind mirror; fall back to Rocky official mirror.
    # Try several rpmfind layouts since they differ by repo (BaseOS vs devel) and naming (debug vs debuginfo).
    return [
        (
            "https://download.rockylinux.org/pub/rocky/"
            f"{minor}/devel/x86_64/debug/tree/Packages/k/"
        )
    ]


def find_el8_debuginfo_rpms(kernel_release: str) -> list[str]:
    """Return debuginfo RPM filenames for an EL8 kernel release.

    Looks for both kernel-debuginfo-<rel>.rpm and
    kernel-debuginfo-common-x86_64-<rel>.rpm across known EL8 mirrors.
    """
    # Prefer standard debuginfo; also try debug-kernel variants if present
    target_sets = [
        [
            f"kernel-debuginfo-{kernel_release}.rpm",
            f"kernel-debuginfo-common-x86_64-{kernel_release}.rpm",
        ],
        [
            f"kernel-debug-debuginfo-{kernel_release}.rpm",
            f"kernel-debug-debuginfo-common-x86_64-{kernel_release}.rpm",
        ],
    ]
    for base in _candidate_bases(kernel_release):
        try:
            entries = _list_dir(base)
        except Exception:
            continue
        # Try each target set in order
        for targets in target_sets:
            found = []
            for t in targets:
                if t in entries:
                    found.append(t)
            if len(found) == len(targets):
                return [base + f for f in found]  # return full URLs
    return []
