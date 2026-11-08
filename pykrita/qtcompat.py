"""Shared Qt binding shim for Krita 5 (PyQt5) and Krita 6 (PyQt6).

Used by ``tfm`` and ``quick_image_search``. Prefer importing from this module
(or the thin package re-exports) so binding differences stay in one place.
"""

import sys

# Krita has already loaded its binding. Never import a second Qt runtime into it.
if "PyQt5.QtCore" in sys.modules:
    from PyQt5 import QtCore, QtGui, QtWidgets
    PYQT6 = False
else:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
        PYQT6 = True
    except ImportError:
        from PyQt5 import QtCore, QtGui, QtWidgets
        PYQT6 = False

# Re-export the public Qt surface so callers stay binding-agnostic.
for _module in (QtCore, QtGui, QtWidgets):
    for _name in dir(_module):
        if not _name.startswith("_"):
            globals().setdefault(_name, getattr(_module, _name))

Qt = QtCore.Qt
pyqtSignal = QtCore.pyqtSignal
QAction = QtGui.QAction if PYQT6 else QtWidgets.QAction
QPalette = QtGui.QPalette
QColor = QtGui.QColor


def exec_(dialog_or_menu, *args):
    """Run a QDialog/QMenu modal loop on both bindings."""
    fn = getattr(dialog_or_menu, "exec", None)
    if fn is None:
        fn = dialog_or_menu.exec_
    return fn(*args)


def event_key_sequence(event):
    """QKeySequence for a QKeyEvent on Qt 5 and Qt 6."""
    comb = getattr(event, "keyCombination", None)
    if comb is not None:
        try:
            return QKeySequence(comb())
        except Exception:
            pass
    mods = event.modifiers()
    key = event.key()
    try:
        return QKeySequence(int(mods) | int(key))
    except TypeError:
        mods = getattr(mods, "value", mods)
        key = getattr(key, "value", key)
        return QKeySequence(int(mods) | int(key))


def _palette_role(name):
    if PYQT6:
        return getattr(QtGui.QPalette.ColorRole, name)
    return getattr(QtGui.QPalette, name)


def user_role():
    role = Qt.ItemDataRole.UserRole if PYQT6 else Qt.UserRole
    return getattr(role, "value", role)


def item_is_user_checkable():
    return Qt.ItemFlag.ItemIsUserCheckable if PYQT6 else Qt.ItemIsUserCheckable


def checked_state():
    return Qt.CheckState.Checked if PYQT6 else Qt.Checked


def unchecked_state():
    return Qt.CheckState.Unchecked if PYQT6 else Qt.Unchecked
