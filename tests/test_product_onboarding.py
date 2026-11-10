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
    path = ROOT / 'pykrita/tfm/backend_status.py'
    spec = importlib.util.spec_from_file_location('backend_status_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tip = module.backend_action_tip
    assert 'tfm_vulkan_worker.exe' in tip('TFM Vulkan worker is not installed next to kritatfm.dll')
    assert 'CPU' in tip('Vulkan worker closed before it was ready')
    assert '.gguf' in tip('BiRefNet model not found: X')
    assert 'TFM_VULKAN_DISABLE' in tip('Vulkan disabled')
    assert tip('ok') == ''


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
