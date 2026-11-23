"""Deploy hygiene: single plugin DLL + no archive trees under live pykrita/tfm."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_deploy():
    path = ROOT / "deploy.py"
    spec = importlib.util.spec_from_file_location("tfm_deploy", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLEAN_IMPORT = """
import sys
import types
from unittest.mock import Mock
from PyQt5.QtWidgets import QApplication, QDockWidget
from pathlib import Path

app = QApplication([])
host = Mock()
host.readSetting.side_effect = lambda group, key, default: default
krita = types.ModuleType("krita")
krita.Krita = types.SimpleNamespace(instance=lambda: host)
krita.Extension = type("Extension", (), {"__init__": lambda self, parent: None})
krita.DockWidget = QDockWidget
krita.DockWidgetFactoryBase = types.SimpleNamespace(DockRight=1)
krita.DockWidgetFactory = lambda factory_id, area, cls: factory_id
sys.modules["krita"] = krita
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import tfm
import tfm_diagnostics
assert Path(tfm.__file__).resolve().is_relative_to(root)
assert Path(tfm_diagnostics.__file__).resolve().is_relative_to(root)
assert host.addExtension.call_count == 1
assert [call.args[0] for call in host.addDockWidgetFactory.call_args_list] == ["tfm_assets", "tfm_quick_image_search"]
"""


class DeployHygieneTests(unittest.TestCase):
    def setUp(self):
        self.deploy = _load_deploy()

    def test_clean_deploy_registers_extension_and_dockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / "batch"
            batch.mkdir()
            for name in ("tfm_color_range.dll", "kritatfm.dll", "tfm_vulkan_worker.exe"):
                (batch / name).write_bytes(b"test")
            resource = root / "resource"
            self.deploy.deploy_tfm(resource, root / "host", (batch, {"batch_id": "test"}))
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", KLOCALAPPDATA=tmp)
            result = subprocess.run(
                [sys.executable, "-I", "-c", CLEAN_IMPORT, str(resource / "pykrita")],
                cwd=tmp, env=env, text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_assert_single_tfm_plugin_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            (plugins / "kritatfm.dll").write_bytes(b"ok")
            self.deploy.assert_single_tfm_plugin(plugins)

    def test_assert_single_tfm_plugin_rejects_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            (plugins / "kritatfm.dll").write_bytes(b"top")
            nested = plugins / "tfm-rollback"
            nested.mkdir()
            (nested / "kritatfm.dll").write_bytes(b"old")
            with self.assertRaises(RuntimeError):
                self.deploy.assert_single_tfm_plugin(plugins)

    def test_evacuate_only_owned_binaries_preserves_every_version(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            plugins = base / "plugins"
            backup = base / "backup"
            nested = plugins / "tfm-rollback"
            nested.mkdir(parents=True)
            foreign = nested / "another-plugin.dll"
            foreign.write_bytes(b"third party")
            own = nested / "kritatfm.dll"
            for content in (b"first", b"second", b"first"):
                own.write_bytes(content)
                self.deploy.evacuate_nested_plugin_dlls(plugins, backup)
            self.assertEqual(foreign.read_bytes(), b"third party")
            self.assertEqual(sorted(p.read_bytes() for p in backup.rglob(own.name)), [b"first", b"second"])

    def test_evacuate_package_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "pykrita" / "tfm"
            archive = root / "TFM" / "archived-pykrita"
            (pkg / "menus").mkdir(parents=True)
            (pkg / "menus" / "dialog.py").write_text("# live\n", encoding="utf-8")
            (pkg / "rollback" / "old.py").parent.mkdir(parents=True)
            (pkg / "rollback" / "old.py").write_text("# old\n", encoding="utf-8")
            filters_rb = pkg / "filters" / "tfm-rollback"
            filters_rb.mkdir(parents=True)
            (filters_rb / "x.py").write_text("# rb\n", encoding="utf-8")

            self.deploy._evacuate_package_archives(pkg, archive)

            self.assertFalse((pkg / "rollback").exists())
            self.assertFalse((pkg / "filters" / "tfm-rollback").exists())
            self.assertTrue((pkg / "menus" / "dialog.py").is_file())
            self.assertTrue((archive / "rollback" / "old.py").is_file())
            self.assertTrue((archive / "filters" / "tfm-rollback" / "x.py").is_file())


if __name__ == "__main__":
    unittest.main()
