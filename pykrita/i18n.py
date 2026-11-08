"""UI strings that follow the Krita / Qt interface language (Chinese vs English)."""

from __future__ import annotations


def ui_is_chinese() -> bool:
    """True when the host UI language is Chinese (zh*)."""
    try:
        from qtcompat import QLocale
    except Exception:
        try:
            from PyQt5.QtCore import QLocale
        except Exception:
            try:
                from PyQt6.QtCore import QLocale
            except Exception:
                return False
    try:
        language = QLocale().language()
        chinese = getattr(QLocale.Language, "Chinese", None)
        if chinese is not None and language == chinese:
            return True
        name = str(QLocale().name() or "").lower()
        return name.startswith("zh")
    except Exception:
        return False


def tr(english: str, chinese: str | None = None) -> str:
    """Return Chinese when the host UI is Chinese, otherwise English."""
    if chinese and ui_is_chinese():
        return chinese
    return english
