from __future__ import annotations

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
    SpinnerColumn,
)
from urllib.request import urlopen, Request


def download_with_progress(url: str, out_path: Path, console: Console) -> None:
    max_retries = 3
    last_err: Optional[str] = None
    for _ in range(1, max_retries + 1):
        req = Request(url, headers={"User-Agent": "kdump-helper/0.1"})
        try:
            console.print(f"[blue]Downloading {out_path.name} from[/] {url}")
            with urlopen(req) as resp:  # nosec - controlled URL
                total_str = resp.getheader("Content-Length")
                total = int(total_str) if total_str and total_str.isdigit() else 0
                columns = [
                    SpinnerColumn(),
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
                    with open(out_path, "wb") as outf:
                        while True:
                            chunk = resp.read(1024 * 64)
                            if not chunk:
                                break
                            outf.write(chunk)
                            progress.update(task_id, advance=len(chunk))
                if total and out_path.stat().st_size != total:
                    last_err = (
                        f"size mismatch: expected {total} got {out_path.stat().st_size}"
                    )
                    continue
                return
        except Exception as e:  # pragma: no cover - network variability
            last_err = str(e)
    from .pkg_manager import PackageManagerError

    raise PackageManagerError(f"Failed to download {url}: {last_err}")


