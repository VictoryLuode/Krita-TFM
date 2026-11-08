"""Qt binding shim for Krita 5 (PyQt5) and Krita 6 (PyQt6)."""
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    PYQT6 = True
except ImportError:
    from PyQt5 import QtCore, QtGui, QtWidgets
    PYQT6 = False

# Re-export the Qt surface used by the plugin. Keeping imports here makes the
# product modules independent of the binding selected by the host.
for _module in (QtCore, QtGui, QtWidgets):
    for _name in dir(_module):
        if not _name.startswith('_'):
            globals().setdefault(_name, getattr(_module, _name))

Qt = QtCore.Qt
QPalette = QtGui.QPalette
QAction = QtGui.QAction if PYQT6 else QtWidgets.QAction


def exec_(widget, *args):
    """Run a modal Qt object on both bindings."""
    method = getattr(widget, 'exec', None)
    if method is None:
        method = widget.exec_
    return method(*args)

