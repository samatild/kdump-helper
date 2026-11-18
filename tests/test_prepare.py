import importlib
import unittest
from unittest.mock import Mock, patch

from kdump_helper.distro import DistroInfo
from kdump_helper.pkg_manager import (
    DnfManager,
    PackageManagerError,
    select_package_manager,
)


prepare_module = importlib.import_module("kdump_helper.commands.prepare")


class PrepareTests(unittest.TestCase):
    def test_azure_linux_uses_native_tools_without_source_build(self):
        manager = Mock()
        info = DistroInfo("azurelinux", "4.0", "Azure Linux 4.0")
        with (
            patch.object(prepare_module, "detect_distro", return_value=info),
            patch.object(prepare_module, "select_package_manager", return_value=manager),
            patch.object(prepare_module, "_ensure_build_deps") as build_deps,
            patch.object(prepare_module, "_build_crash_from_source") as build,
        ):
            prepare_module.prepare()
        manager.update_metadata.assert_called_once_with()
        self.assertEqual(
            manager.install.call_args_list,
            [
                unittest.mock.call(["kexec-tools", "makedumpfile", "cpio", "rpm"]),
                unittest.mock.call(["crash", "gdb"]),
            ],
        )
        build_deps.assert_not_called()
        build.assert_not_called()

    def test_azure_linux_package_failure_is_not_hidden(self):
        manager = Mock()
        manager.install.side_effect = [None, PackageManagerError("gdb unavailable")]
        info = DistroInfo("azurelinux", "4.0", "Azure Linux 4.0")
        with (
            patch.object(prepare_module, "detect_distro", return_value=info),
            patch.object(prepare_module, "select_package_manager", return_value=manager),
            patch.object(prepare_module, "_build_crash_from_source") as build,
        ):
            with self.assertRaisesRegex(PackageManagerError, "gdb unavailable"):
                prepare_module.prepare()
        build.assert_not_called()

    def test_rhel_retains_source_build(self):
        manager = Mock()
        info = DistroInfo("rhel", "9", "Red Hat Enterprise Linux 9")
        with (
            patch.object(prepare_module, "detect_distro", return_value=info),
            patch.object(prepare_module, "select_package_manager", return_value=manager),
            patch.object(prepare_module, "_ensure_build_deps") as build_deps,
            patch.object(prepare_module, "_build_crash_from_source") as build,
        ):
            prepare_module.prepare()
        build_deps.assert_called_once_with("rhel", manager)
        build.assert_called_once_with(manager)
        manager.install.assert_called_once_with(["kexec-tools", "cpio", "rpm-build"])

    def test_azure_linux_selects_dnf_even_if_apt_is_present(self):
        with patch("kdump_helper.pkg_manager.shutil.which", return_value="/usr/bin/tool"):
            manager = select_package_manager("azurelinux")
        self.assertIsInstance(manager, DnfManager)
        self.assertEqual(manager.binary, "dnf")


if __name__ == "__main__":
    unittest.main()
