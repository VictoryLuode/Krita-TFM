"""Bootstrap the installed Krita binding only inside an isolated host process."""
import os
from pathlib import Path
import sys

_DLL_HANDLES = []


def configure():
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError('Krita 5.3 offline checks require Python 3.13')
    value = os.environ.get('KRITA_ROOT', '')
    root = Path(value) if value else None
    if root is None or not (root / 'lib/site-packages/PyQt5').is_dir():
        raise RuntimeError('Set KRITA_ROOT to the installed Krita 5.3 Qt5 directory')
    _DLL_HANDLES.append(os.add_dll_directory(str(root / 'bin')))
    # PyQt's own bootstrap scans PATH; keep it on the same Qt build as its pyd.
    os.environ['PATH'] = str(root / 'bin') + os.pathsep + os.environ.get('PATH', '')
    os.environ['QT_PLUGIN_PATH'] = str(root / 'bin')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.path.insert(0, str(root / 'lib/site-packages'))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pykrita'))
    from PyQt5.QtCore import QLocale
    from PyQt5.QtWidgets import QApplication
    QLocale.setDefault(QLocale(os.environ.get('TFM_TEST_LOCALE', 'en_US')))
    return QApplication.instance() or QApplication([])


def run_check(script, *arguments):
    """Run without leaking modules, Qt libraries or environment into pytest."""
    import subprocess
    import tempfile
    import pytest
    if sys.version_info[:2] != (3, 13):
        pytest.skip('offline Krita checks require Python 3.13')
    if not os.environ.get('KRITA_ROOT'):
        pytest.skip('KRITA_ROOT not configured; host check was not executed')
    with tempfile.TemporaryDirectory(prefix='tfm-host-check-') as temporary:
        env = dict(os.environ, KLOCALAPPDATA=temporary, TMPDIR=temporary)
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-u', str(script), *map(str, arguments)],
                                env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=120)
    assert result.returncode == 0, f'host exit={result.returncode:#x}\n' + result.stdout + result.stderr
