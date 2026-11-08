"""Keep popup focus/deferred-delete events inside the test that created them."""
import sys
from pathlib import Path

import pytest

# Shared qtcompat.py lives under pykrita/; put it on sys.path for package imports.
_PYKRITA = Path(__file__).resolve().parents[1] / "pykrita"
if str(_PYKRITA) not in sys.path:
    sys.path.insert(0, str(_PYKRITA))

from qt_test_binding import QApplication, QCoreApplication, QEvent

@pytest.fixture(autouse=True)
def drain_widget_events():
    yield
    app = QApplication.instance()
    if app is not None:
        for widget in app.topLevelWidgets():
            widget.close()
        for _ in range(3):
            app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
