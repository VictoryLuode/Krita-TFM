"""Keep popup focus/deferred-delete events inside the test that created them."""
import pytest
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
