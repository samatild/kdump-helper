from contextlib import ExitStack
import importlib
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from kdump_helper.cli import app
from kdump_helper.distro import DistroInfo
from kdump_helper.pkg_manager import PackageManagerError


analyze_module = importlib.import_module("kdump_helper.commands.analyze")
RELEASE = "6.18.57-1.11.azl4.x86_64"


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name)
        self.vmcore = self.target / "dump with spaces"
        self.vmcore.touch()
        self.symbols = self.target / "vmlinux"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(
            analyze_module, "detect_distro",
            return_value=DistroInfo("azurelinux", "4.0", "Azure Linux 4.0"),
        ))
        self.stack.enter_context(patch.object(
            analyze_module, "extract_release_from_vmcore", return_value=RELEASE,
        ))
        self.stack.enter_context(patch.object(
            analyze_module, "check_existing_debug_symbols", return_value=None,
        ))
        self.stack.enter_context(patch(
            "kdump_helper.debug_symbols.check_existing_in_target", return_value=None,
        ))
        self.stack.enter_context(patch.object(
            analyze_module, "find_vmlinux_paths", return_value=[],
        ))
        self.install = self.stack.enter_context(patch.object(
            analyze_module, "install_kernel_debuginfo",
        ))
        self.download = self.stack.enter_context(patch.object(
            analyze_module, "download_azurelinux_debuginfo",
            return_value=[self.symbols],
        ))
        self.runner = CliRunner()
        self.args = [
            "analyze", "--vmcore", str(self.vmcore), "--target", str(self.target),
        ]

    def test_azure_dump_fetches_matching_symbols_without_full_package_install(self):
        result = self.runner.invoke(app, self.args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.download.call_args.args[:2], (RELEASE, self.target))
        self.install.assert_not_called()
        self.assertIn("Symbols ready:", result.output)
        self.assertIn("Open the dump with:", result.output)
        self.assertIn(
            shlex.join(["crash", str(self.symbols), str(self.vmcore)]), result.output,
        )

    def test_download_failure_exits_nonzero(self):
        self.download.side_effect = PackageManagerError("not enough disk space")
        result = self.runner.invoke(app, self.args)
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("not enough disk space", result.output)
        self.assertNotIn("Symbols ready:", result.output)

    def test_no_matching_symbols_exits_nonzero(self):
        self.install.side_effect = PackageManagerError("no matching package")
        result = self.runner.invoke(
            app, ["analyze", "--release", "6.1.0-custom", "--target", str(self.target)],
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("All methods failed", result.output)
        self.download.assert_not_called()

    def test_crash_launch_failure_exits_nonzero(self):
        with patch.object(
            analyze_module, "launch_crash",
            side_effect=PackageManagerError("crash exited with status 1"),
        ):
            result = self.runner.invoke(app, self.args + ["--launch"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("crash exited with status 1", result.output)


if __name__ == "__main__":
    unittest.main()
