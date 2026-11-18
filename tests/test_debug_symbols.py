from contextlib import ExitStack
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rich.console import Console

from kdump_helper import debug_symbols
from kdump_helper.pkg_manager import PackageManagerError


RELEASE = "6.18.57-1.11.azl4.x86_64"


class AzureSymbolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name)
        self.member = f"/usr/lib/debug/lib/modules/{RELEASE}/vmlinux"
        self.destination = self.target / self.member.lstrip("/")
        self.console = Console(file=io.StringIO())
        self.data = b"vmlinux"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(
            debug_symbols.shutil, "which", return_value="/usr/bin/tool",
        ))
        self.stack.enter_context(patch.object(
            debug_symbols.shutil, "disk_usage", return_value=SimpleNamespace(free=1000),
        ))
        self.download = self.stack.enter_context(patch(
            "kdump_helper.net_utils.download_with_progress",
        ))
        self.metadata = self.stack.enter_context(patch.object(
            debug_symbols, "_run",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=f"{self.member}\t{len(self.data)}\n",
            ),
        ))
        self.extract = self.stack.enter_context(patch.object(
            debug_symbols, "_run_with_progress", side_effect=self.extract_vmlinux,
        ))

    def extract_vmlinux(self, command, description, console):
        Path(command[-1]).write_bytes(self.data)
        self.assertEqual(command[1:3], ["-o", "pipefail"])
        self.assertEqual(command[-2], "." + self.member)
        return subprocess.CompletedProcess(command, 0, stdout="")

    def test_extracts_only_matching_vmlinux_and_cleans_download(self):
        paths = debug_symbols.download_azurelinux_debuginfo(
            RELEASE, self.target, self.console,
        )
        self.assertEqual(paths, [self.destination])
        self.assertEqual(self.destination.read_bytes(), self.data)
        url, rpm_path, _ = self.download.call_args.args
        self.assertEqual(
            url,
            "https://packages.microsoft.com/azurelinux/4/prod/base/debuginfo/"
            f"x86_64/Packages/k/kernel-debuginfo-{RELEASE}.rpm",
        )
        self.assertFalse(rpm_path.parent.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_reuses_previously_extracted_symbols(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(self.data)
        self.assertEqual(
            debug_symbols.download_azurelinux_debuginfo(
                RELEASE, self.target, self.console,
            ),
            [self.destination],
        )
        self.download.assert_not_called()

    def test_insufficient_space_fails_before_extraction(self):
        with patch.object(
            debug_symbols.shutil, "disk_usage", return_value=SimpleNamespace(free=0),
        ):
            with self.assertRaisesRegex(PackageManagerError, "Not enough space"):
                debug_symbols.download_azurelinux_debuginfo(
                    RELEASE, self.target, self.console,
                )
        self.extract.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_missing_exact_vmlinux_fails(self):
        self.metadata.return_value.stdout = "/usr/lib/debug/other/vmlinux\t100\n"
        with self.assertRaisesRegex(PackageManagerError, "does not contain"):
            debug_symbols.download_azurelinux_debuginfo(
                RELEASE, self.target, self.console,
            )
        self.extract.assert_not_called()

    def test_partial_extraction_is_not_cached(self):
        def partial(command, description, console):
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, stdout="archive error")

        self.extract.side_effect = partial
        with self.assertRaisesRegex(PackageManagerError, "archive error"):
            debug_symbols.download_azurelinux_debuginfo(
                RELEASE, self.target, self.console,
            )
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])


class VmcoreTests(unittest.TestCase):
    def test_reads_compressed_dump_metadata_without_creating_sidecar(self):
        dump = Path("/dump with spaces/vmcore")
        with (
            patch.object(debug_symbols.shutil, "which", return_value="/usr/bin/crash"),
            patch.object(debug_symbols, "_run", return_value=subprocess.CompletedProcess(
                [], 0, stdout=RELEASE + "\n",
            )) as run,
        ):
            self.assertEqual(debug_symbols.extract_release_from_vmcore(dump), RELEASE)
        run.assert_called_once_with(["/usr/bin/crash", "--osrelease", str(dump)])

    def test_failed_crash_process_is_not_success(self):
        with (
            patch.object(debug_symbols.shutil, "which", return_value="/usr/bin/crash"),
            patch.object(debug_symbols.subprocess, "run",
                         return_value=subprocess.CompletedProcess([], 1)),
        ):
            with self.assertRaisesRegex(PackageManagerError, "status 1"):
                debug_symbols.launch_crash(
                    Path("vmlinux"), Path("vmcore"), Console(file=io.StringIO()),
                )

    def test_verbose_progress_command_does_not_deadlock(self):
        code = """
import io
import sys
from rich.console import Console
from kdump_helper.debug_symbols import _run_with_progress
result = _run_with_progress(
    [sys.executable, "-c", "print('x' * 262144)"],
    "Verbose command",
    Console(file=io.StringIO()),
)
assert result.returncode == 0
assert len(result.stdout) == 262145
"""
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
