"""Qt binding shim - one import surface for Krita 5 (PyQt5 / Qt 5) and
Krita 6 (PyQt6 / Qt 6).

Krita 6 moved its Python plugins to PyQt6, i.e. Qt 6. Three things changed that
this module absorbs so the rest of the plugin stays version-agnostic:

* ``QAction`` lives in ``QtGui`` on Qt 6 (``QtWidgets.QAction`` is gone);
* ``exec_()`` was removed in favour of ``exec()``;
* every enum has to be spelled through its scope - ``Qt.AlignmentFlag.AlignLeft``
  instead of ``Qt.AlignLeft`` - and the key/modifier flags no longer accept
  ``int()`` arithmetic.

The scoped enum spelling also works on PyQt5, so the plugin code uses it
everywhere and only the imports go through this module.
"""

import sys

if "PyQt5.QtCore" in sys.modules:
    from PyQt5 import QtCore, QtGui, QtWidgets
    PYQT6 = False
else:
    try:  # Krita 6: PyQt6 / Qt 6
        from PyQt6 import QtCore, QtGui, QtWidgets
        PYQT6 = True
    except ImportError:  # Krita 5: PyQt5 / Qt 5
        from PyQt5 import QtCore, QtGui, QtWidgets
        PYQT6 = False

# --- QtCore ---------------------------------------------------------------
Qt = QtCore.Qt
QEvent = QtCore.QEvent
QObject = QtCore.QObject
QPoint = QtCore.QPoint
QPointF = QtCore.QPointF
QRect = QtCore.QRect
QRectF = QtCore.QRectF
QSize = QtCore.QSize
QStandardPaths = QtCore.QStandardPaths
QTimer = QtCore.QTimer
QUrl = QtCore.QUrl

# --- QtGui ----------------------------------------------------------------
QBrush = QtGui.QBrush
QColor = QtGui.QColor
QCursor = QtGui.QCursor
QDesktopServices = QtGui.QDesktopServices
QFont = QtGui.QFont
QIcon = QtGui.QIcon
QKeySequence = QtGui.QKeySequence
QPainter = QtGui.QPainter
QPalette = QtGui.QPalette
QPen = QtGui.QPen
QPixmap = QtGui.QPixmap
QImage = QtGui.QImage
pyqtSignal = QtCore.pyqtSignal
QRadioButton = QtWidgets.QRadioButton
QSlider = QtWidgets.QSlider
QSpinBox = QtWidgets.QSpinBox

# --- QtWidgets ------------------------------------------------------------
QAbstractItemView = QtWidgets.QAbstractItemView
QApplication = QtWidgets.QApplication
QByteArray = QtCore.QByteArray
QMimeData = QtCore.QMimeData
QCheckBox = QtWidgets.QCheckBox
QComboBox = QtWidgets.QComboBox
QDialog = QtWidgets.QDialog
QDialogButtonBox = QtWidgets.QDialogButtonBox
QFileDialog = QtWidgets.QFileDialog
QFrame = QtWidgets.QFrame
QGroupBox = QtWidgets.QGroupBox
QHBoxLayout = QtWidgets.QHBoxLayout
QInputDialog = QtWidgets.QInputDialog
QKeySequenceEdit = QtWidgets.QKeySequenceEdit
QLabel = QtWidgets.QLabel
QLineEdit = QtWidgets.QLineEdit
QListWidget = QtWidgets.QListWidget
QListWidgetItem = QtWidgets.QListWidgetItem
QMenu = QtWidgets.QMenu
QMessageBox = QtWidgets.QMessageBox
QPlainTextEdit = QtWidgets.QPlainTextEdit
QPushButton = QtWidgets.QPushButton
QRadioButton = QtWidgets.QRadioButton
QSlider = QtWidgets.QSlider
QSpinBox = QtWidgets.QSpinBox
QStyle = QtWidgets.QStyle
QStyledItemDelegate = QtWidgets.QStyledItemDelegate
QTextEdit = QtWidgets.QTextEdit
QTreeWidget = QtWidgets.QTreeWidget
QTreeWidgetItem = QtWidgets.QTreeWidgetItem
QVBoxLayout = QtWidgets.QVBoxLayout
QWidget = QtWidgets.QWidget
QWidgetAction = QtWidgets.QWidgetAction

# QAction moved from QtWidgets (Qt 5) to QtGui (Qt 6).
QAction = QtGui.QAction if PYQT6 else QtWidgets.QAction


# --- helpers that differ between the two bindings -------------------------
def exec_(dialog_or_menu, *args):
    """Run a QDialog/QMenu modal loop.

    PyQt6 dropped ``exec_()``; ``exec()`` exists in PyQt5 as well, but not in
    the older PyQt5 releases still shipped with early Krita 5 builds, so both
    spellings are tried.
    """
    fn = getattr(dialog_or_menu, "exec", None)
    if fn is None:
        fn = dialog_or_menu.exec_
    return fn(*args)


def event_key_sequence(event):
    """QKeySequence for a QKeyEvent.

    Qt 6 wraps key and modifiers in distinct enum types, so ``int(mods) | key``
    (the Qt 5 idiom) raises TypeError; ``QKeyEvent.keyCombination()`` is the
    documented replacement. PyQt5 has no keyCombination(), hence the fallback.
    """
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
