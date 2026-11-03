"""Deploy hygiene: single plugin DLL + no archive trees under live pykrita/tfm."""

from __future__ import annotations

import importlib.util
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


class DeployHygieneTests(unittest.TestCase):
    def setUp(self):
        self.deploy = _load_deploy()

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
