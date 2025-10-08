from dataclasses import dataclass
from typing import Optional

import distro as distro_lib


@dataclass(frozen=True)
class DistroInfo:
    id: str
    version_id: Optional[str]
    pretty_name: Optional[str]

    def is_rhel_like(self) -> bool:
        rid = self.id.lower()
        return rid in {"rhel", "redhat", "centos", "rocky", "almalinux"}

    def is_sles_like(self) -> bool:
        rid = self.id.lower()
        return rid in {"sles", "suse", "opensuse-leap", "opensuse-tumbleweed"}

    def is_debian(self) -> bool:
        return self.id.lower() == "debian"

    def is_ubuntu(self) -> bool:
        return self.id.lower() == "ubuntu"


def detect_distro() -> DistroInfo:
    return DistroInfo(
        id=distro_lib.id() or "unknown",
        version_id=distro_lib.version(best=True) or None,
        pretty_name=distro_lib.name(pretty=True) or None,
    )

