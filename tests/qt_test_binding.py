"""Use the installed Qt binding without importing the Krita plugin entry point."""
try:
    from PyQt6 import QtCore, QtGui, QtWidgets, QtTest
except ImportError:
    from PyQt5 import QtCore, QtGui, QtWidgets, QtTest

for _module in (QtCore, QtGui, QtWidgets, QtTest):
    for _name in dir(_module):
        if not _name.startswith('_'):
            globals().setdefault(_name, getattr(_module, _name))
