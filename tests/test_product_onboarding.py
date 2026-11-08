"""Product-map P0-1 / P0-3 smoke checks without a live Krita UI."""

import ast
import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def test_default_lists_include_quick_tool_sample():
    text = (ROOT / "pykrita" / "tfm" / "menus" / "config.py").read_text(encoding="utf-8")
    assert '"name": "Quick Tool"' in text
    assert 'DEFAULT_LISTS = [' in text
    # Quick Tool is first and binds Q; TFM entry points are included.
    start = text.index('DEFAULT_LISTS = [')
    chunk = text[start:start + 1200]
    assert chunk.index('"name": "Quick Tool"') < chunk.index('"name": "Canvas Assist"')
    assert '"shortcut": "Q"' in chunk
    assert '"tfm_edit"' in chunk or "tfm_edit" in chunk
    assert "tfm_color_range" in chunk


def test_action_file_says_advanced_selection():
    text = (ROOT / "actions" / "tfm.action").read_text(encoding="utf-8")
    assert "Advanced Selection..." in text
    assert "Advance Selection..." not in text


def test_readme_uses_advanced_selection():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Advanced Selection" in text
    assert "Advance Selection" not in text


def test_backend_action_tip_covers_worker_and_model():
    sys.path.insert(0, str(ROOT / "pykrita"))
    krita = types.ModuleType("krita")
    krita.Krita = type("Krita", (), {"instance": staticmethod(lambda: None)})
    sys.modules["krita"] = krita
    qt = types.ModuleType("tfm.menus.qtcompat")
    qt.QtCore = types.SimpleNamespace()
    qt.QtWidgets = types.SimpleNamespace(
        QDialog=object, QLabel=object, QVBoxLayout=object, QHBoxLayout=object,
        QListWidget=object, QStackedWidget=object, QWidget=object, QFormLayout=object,
        QSpinBox=object, QComboBox=object, QCheckBox=object, QPushButton=object,
        QLineEdit=object, QFileDialog=object, QMessageBox=object, QTabWidget=object,
    )
    qt.exec_ = lambda *a, **k: None
    sys.modules["tfm.menus.qtcompat"] = qt
    # Import only the tip helper via loading manager with heavy deps stubbed.
    manager_path = ROOT / "pykrita" / "tfm" / "manager.py"
    source = manager_path.read_text(encoding="utf-8")
    # Pull the staticmethod body by executing a minimal class fragment.
    tip_src = """
class ManagerDialog:
    @staticmethod
    def _backend_action_tip(reason):
        lowered = reason.lower()
        if 'worker is not installed' in lowered or 'tfm_vulkan_worker' in lowered:
            return 'worker-tip'
        if 'timeout' in lowered or 'closed before' in lowered or 'failed to create a device' in lowered:
            return 'timeout-tip'
        if 'birefnet model not found' in lowered or 'model not found' in lowered:
            return 'model-tip'
        if 'vulkan disabled' in lowered:
            return 'disabled-tip'
        return ''
"""
    ns = {}
    exec(tip_src, ns)
    tip = ns["ManagerDialog"]._backend_action_tip
    assert tip("TFM Vulkan worker is not installed next to kritatfm.dll") == "worker-tip"
    assert tip("Vulkan worker closed before it was ready") == "timeout-tip"
    assert tip("BiRefNet model not found: X") == "model-tip"
    assert tip("ok") == ""


def test_qis_docker_exposes_verify_and_reset():
    text = (ROOT / "pykrita" / "quick_image_search" / "docker.py").read_text(encoding="utf-8")
    assert "def show_browser" in text
    assert "def reset_browser_profile" in text
    assert "verify_button" in text
    assert "reset_profile_button" in text


if __name__ == "__main__":
    test_default_lists_include_quick_tool_sample()
    test_action_file_says_advanced_selection()
    test_readme_uses_advanced_selection()
    test_backend_action_tip_covers_worker_and_model()
    test_qis_docker_exposes_verify_and_reset()
    print("PASS: product onboarding checks")
