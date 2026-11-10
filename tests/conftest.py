"""Keep popup focus/deferred-delete events inside the test that created them."""
import sys
import os
from pathlib import Path

import pytest

# Shared qtcompat.py lives under pykrita/; put it on sys.path for package imports.
_PYKRITA = Path(__file__).resolve().parents[1] / "pykrita"
if str(_PYKRITA) not in sys.path:
    sys.path.insert(0, str(_PYKRITA))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from qt_test_binding import QApplication, QCoreApplication, QEvent, QLocale, QStandardPaths

QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setOrganizationName('TFM tests')
QCoreApplication.setApplicationName('TFM isolated tests')
QLocale.setDefault(QLocale(os.environ.get('TFM_TEST_LOCALE', 'en_US')))


def pytest_addoption(parser):
    parser.addoption('--run-experimental', action='store_true', help='Collect non-production Relight research checks')


def pytest_ignore_collect(collection_path, config):
    if collection_path.name.startswith('test_relight_') and not config.getoption('--run-experimental'):
        return True


@pytest.fixture(autouse=True)
def restore_process_globals():
    modules = {name: module for name, module in sys.modules.items()
               if name == 'krita' or name == 'tfm' or name.startswith('tfm.')}
    paths = list(sys.path)
    locale = QLocale()
    # Lazy imports inside the search UI need the same fake as its loaded module.
    # Scope it to the test instead of leaving it installed during collection.
    search_fixture = sys.modules.get('test_docker')
    if search_fixture is not None:
        sys.modules['krita'] = search_fixture.FAKE
    yield
    for name in list(sys.modules):
        if name == 'krita' or name == 'tfm' or name.startswith('tfm.'):
            if name not in modules:
                sys.modules.pop(name, None)
    sys.modules.update(modules)
    sys.path[:] = paths
    QLocale.setDefault(locale)

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
