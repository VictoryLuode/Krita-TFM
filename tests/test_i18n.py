"""Locale helper returns Chinese only for zh* UI languages."""

import importlib.util
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pykrita"))

spec = importlib.util.spec_from_file_location("tfm_i18n_under_test", ROOT / "pykrita" / "i18n.py")
i18n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i18n)


def test_tr_english_default():
    with mock.patch.object(i18n, "ui_is_chinese", return_value=False):
        assert i18n.tr("Hello", "你好") == "Hello"


def test_tr_chinese_when_ui_chinese():
    with mock.patch.object(i18n, "ui_is_chinese", return_value=True):
        assert i18n.tr("Hello", "你好") == "你好"


def test_tr_falls_back_without_chinese():
    with mock.patch.object(i18n, "ui_is_chinese", return_value=True):
        assert i18n.tr("Hello") == "Hello"
