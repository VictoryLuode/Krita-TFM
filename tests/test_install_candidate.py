import importlib.util
import os
from pathlib import Path
import tempfile
from unittest import mock

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tfm_install_candidate', root / 'install_candidate.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
    resource = Path(tmp)
    unrelated = resource / 'pykrita' / 'menubelt' / 'config.json'
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'keep-user-data')
    count = installer.stage(resource)
    assert count > 10
    assert (resource / 'pykrita' / 'tfm' / '__init__.py').is_file()
    assert (resource / 'actions' / 'tfm.action').is_file()
    assert (resource / 'pykrita' / 'tfm' / 'native' / 'tfm_color_range.dll').read_bytes() == (root / 'pykrita' / 'tfm' / 'native' / 'tfm_color_range.dll').read_bytes()
    assert unrelated.read_bytes() == b'keep-user-data'
    try:
        installer.stage(resource)
        raise AssertionError('existing installation was overwritten')
    except FileExistsError:
        pass
    assert unrelated.read_bytes() == b'keep-user-data'

with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
    resource = Path(tmp)
    with mock.patch.object(installer, 'digest', side_effect=OSError('simulated verification failure')):
        try:
            installer.stage(resource)
            raise AssertionError('verification failure was ignored')
        except OSError:
            pass
    assert not list(resource.rglob('*.py'))
    assert not (resource / 'pykrita' / 'tfm.desktop').exists()
    assert not (resource / 'pykrita' / 'tfm').exists()
    assert installer.stage(resource) > 10

with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
    resource = Path(tmp)
    shared = resource / 'pykrita'
    shared.mkdir()
    sentinel = shared / 'other-plugin.txt'
    sentinel.write_text('keep', encoding='utf-8')
    with mock.patch.object(installer, 'digest', side_effect=OSError('simulated failure')):
        try:
            installer.stage(resource)
            raise AssertionError('verification failure was ignored')
        except OSError:
            pass
    assert sentinel.read_text(encoding='utf-8') == 'keep'
    assert not (shared / 'tfm').exists()
    assert installer.stage(resource) > 10

with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
    base = Path(tmp)
    active = base / 'active'
    active.mkdir()
    (base / 'kritarc').write_text('ResourceDirectory=' + str(active), encoding='utf-8')
    with mock.patch.dict(os.environ, {'KLOCALAPPDATA': str(base)}):
        for destination in (active, base):
            try:
                installer.stage(destination)
                raise AssertionError('active resource overlap was accepted')
            except ValueError:
                pass
    assert not (active / 'pykrita').exists()

with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
    base = Path(tmp)
    incomplete = base / 'incomplete'
    incomplete.mkdir()
    destination = base / 'destination'
    destination.mkdir()
    with mock.patch.object(installer, 'ROOT', incomplete):
        try:
            installer.stage(destination)
            raise AssertionError('incomplete source was accepted')
        except FileNotFoundError as error:
            assert 'tfm/__init__.py' in str(error).replace('\\', '/')
    assert not list(destination.iterdir())

print('PASS: isolated staging, collision refusal, user data preservation, failed-copy cleanup, active resource guard, missing entry rejection')
