"""Small Qt 5/6 compatibility surface for the FxManager dialog."""

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

Qt = QtCore.Qt
QApplication = QtWidgets.QApplication
QCheckBox = QtWidgets.QCheckBox
QComboBox = QtWidgets.QComboBox
QDoubleSpinBox = QtWidgets.QDoubleSpinBox
QFormLayout = QtWidgets.QFormLayout
QScrollArea = QtWidgets.QScrollArea
QDialog = QtWidgets.QDialog
QDialogButtonBox = QtWidgets.QDialogButtonBox
QFrame = QtWidgets.QFrame
QGroupBox = QtWidgets.QGroupBox
QHBoxLayout = QtWidgets.QHBoxLayout
QLabel = QtWidgets.QLabel
QLineEdit = QtWidgets.QLineEdit
QListWidget = QtWidgets.QListWidget
QListWidgetItem = QtWidgets.QListWidgetItem
QAbstractItemView = QtWidgets.QAbstractItemView
QMenu = QtWidgets.QMenu
QInputDialog = QtWidgets.QInputDialog
QPushButton = QtWidgets.QPushButton
QSplitter = QtWidgets.QSplitter
QTextBrowser = QtWidgets.QTextBrowser
QVBoxLayout = QtWidgets.QVBoxLayout
QWidget = QtWidgets.QWidget
QPalette = QtGui.QPalette
QColor = QtGui.QColor


def _palette_role(name):
    if PYQT6:
        return getattr(QtGui.QPalette.ColorRole, name)
    return getattr(QtGui.QPalette, name)


def exec_(widget):
    fn = getattr(widget, "exec", None) or widget.exec_
    return fn()


def user_role():
    role = Qt.ItemDataRole.UserRole if PYQT6 else Qt.UserRole
    return getattr(role, "value", role)


def item_is_user_checkable():
    flag = Qt.ItemFlag.ItemIsUserCheckable if PYQT6 else Qt.ItemIsUserCheckable
    return flag


def checked_state():
    return Qt.CheckState.Checked if PYQT6 else Qt.Checked


def unchecked_state():
    return Qt.CheckState.Unchecked if PYQT6 else Qt.Unchecked
