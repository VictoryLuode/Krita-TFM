"""Exercise paths and writes from the staged copy in an isolated process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

import pytest

def check_child(resource):
    resource = Path(resource).resolve()
    from host_runtime import configure
    app_instance = configure()
    sys.path.insert(0, str(resource / 'pykrita'))
    import types
    fake = types.ModuleType('krita')
    class App:
        def addExtension(self, extension): pass
    app = App()
    class Krita:
        @staticmethod
        def instance(): return app
    class Extension:
        def __init__(self, parent): pass
    fake.Krita, fake.Extension, fake.Palette = Krita, Extension, type('Palette', (), {})
    sys.modules['krita'] = fake
    import tfm
    from tfm.menus import config
    from tfm.filters import settings
    assert Path(tfm.__file__).resolve().is_relative_to(resource.resolve())
    assert Path(config.CONFIG_FILE).resolve() == resource / 'TFM' / 'config.json'
    assert Path(settings._config_path()).resolve() == resource / 'TFM' / 'settings.json'
    assert config.save_config('', [{'name': 'Test', 'items': []}])
    assert settings.save({'managed_filters': ['tfm_bloom']})
    assert Path(config.CONFIG_FILE).is_file()
    assert Path(settings._config_path()).is_file()
    print('PASS: staged package uses isolated menu and filter settings')

def main():
    import importlib.util
    spec = importlib.util.spec_from_file_location('installer', ROOT / 'install_candidate.py')
    installer = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(installer)
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
        base = Path(tmp)
        resource = base / 'resource'
        resource.mkdir()
        installer.stage(resource)
        profile = base / 'profile'
        profile.mkdir()
        (profile / 'kritarc').write_text('ResourceDirectory=' + str(resource) + '\n', encoding='utf-8')
        env = dict(os.environ, KLOCALAPPDATA=str(profile))
        subprocess.run([sys.executable, str(Path(__file__).resolve()), str(resource)], env=env, check=True)


@pytest.mark.host
def test_staged_paths():
    from host_runtime import run_check
    run_check(Path(__file__).resolve())

if __name__ == "__main__":
    if len(sys.argv) == 2:
        check_child(sys.argv[1])
    else:
        main()
