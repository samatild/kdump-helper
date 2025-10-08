from __future__ import annotations

import re


def list_centos7_x86_64_debuginfo() -> list[str]:
    from urllib.request import urlopen, Request

    base_url = "http://debuginfo.centos.org/7/x86_64/"
    req = Request(base_url, headers={"User-Agent": "kdump-helper/0.1"})
    with urlopen(req) as resp:  # nosec - controlled URL
        html = resp.read().decode("utf-8", "ignore")
    # crude href extraction
    matches = re.findall(r'href="([^"\s]+\.rpm)"', html)
    return matches


def find_centos7_debuginfo_rpms(kernel_release: str) -> list[str]:
    """Return the debuginfo RPM filenames for a given EL7 kernel release.

    Looks for both kernel-debuginfo-<rel>.rpm and
    kernel-debuginfo-common-x86_64-<rel>.rpm in the CentOS 7 debuginfo listing.
    """
    files = list_centos7_x86_64_debuginfo()
    exact = []
    want = [
        f"kernel-debuginfo-{kernel_release}.rpm",
        f"kernel-debuginfo-common-x86_64-{kernel_release}.rpm",
    ]
    for w in want:
        for f in files:
            if f == w:
                exact.append(f)
                break
    return exact


