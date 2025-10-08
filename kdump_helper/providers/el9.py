from __future__ import annotations

import re


def _list_dir(url: str) -> list[str]:
    from urllib.request import urlopen, Request

    req = Request(url, headers={"User-Agent": "kdump-helper/0.1"})
    with urlopen(req) as resp:  # nosec - controlled URL
        html = resp.read().decode("utf-8", "ignore")
    return re.findall(r'href="([^"\s]+)"', html)


def _el9_minor_path(kernel_release: str) -> str:
    """Return minor path like '9.4' from a release ending in .el9_4."""
    m = re.search(r"\.el9_(\d+)", kernel_release)
    if m:
        return f"9.{m.group(1)}"
    return "9"


def _candidate_bases(kernel_release: str) -> list[str]:
    minor = _el9_minor_path(kernel_release)
    # Rocky devel debug tree for EL9
    return [
        f"https://download.rockylinux.org/pub/rocky/{minor}/devel/x86_64/debug/tree/Packages/k/",
    ]


def find_el9_debuginfo_rpms(kernel_release: str) -> list[str]:
    """Return URLs of debuginfo RPMs for an EL9 kernel release from Rocky mirrors."""
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
        for targets in target_sets:
            found = [t for t in targets if t in entries]
            if len(found) == len(targets):
                return [base + f for f in found]
    return []


