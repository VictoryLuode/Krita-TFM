"""Stage TFM Python resources into an empty, isolated Krita resource directory.

This only copies the resource-side package (pykrita/tfm, desktop file, actions,
and tfm_color_range.dll). Native filter binaries kritatfm.dll and
tfm_vulkan_worker.exe must be installed separately into the Krita install
lib/kritaplugins/ folder, or packed with package_release.py.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def stage(destination):
    destination = Path(destination).resolve()
    if not destination.is_dir():
        raise ValueError('Destination resource directory must already exist')
    local = os.environ.get('KLOCALAPPDATA') or os.environ.get('LOCALAPPDATA')
    if local:
        kritarc = Path(local) / 'kritarc'
        if kritarc.is_file():
            for line in kritarc.read_text(encoding='utf-8', errors='replace').splitlines():
                key, sep, value = line.partition('=')
                if sep and key.strip().lower() == 'resourcedirectory':
                    active = Path(value.strip()).resolve()
                    if destination == active or active in destination.parents or destination in active.parents:
                        raise ValueError('Destination overlaps the active Krita resource directory')
    targets = [destination / 'pykrita' / 'tfm',
               destination / 'pykrita' / 'tfm.desktop',
               destination / 'actions' / 'tfm.action']
    if any(path.exists() for path in targets):
        raise FileExistsError('TFM already exists in the destination; refusing to overwrite')
    package = ROOT / 'pykrita' / 'tfm'
    required = [package / '__init__.py', package / 'manager.py',
                package / 'menus' / 'menubelt.py', package / 'menus' / 'config.py',
                package / 'menus' / 'dialog.py', package / 'menus' / 'shortcuts.py',
                package / 'filters' / 'dialog.py', package / 'filters' / 'settings.py',
                package / 'native' / 'tfm_color_range.dll',
                ROOT / 'pykrita' / 'tfm.desktop', ROOT / 'actions' / 'tfm.action']
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError('Missing required TFM files: ' + ', '.join(missing))
    sources = [(p, targets[0] / p.relative_to(ROOT / 'pykrita' / 'tfm'))
               for p in (ROOT / 'pykrita' / 'tfm').rglob('*')
               if p.is_file() and (p.suffix in ('.py', '.html') or p == package / 'native' / 'tfm_color_range.dll') and '__pycache__' not in p.parts]
    sources.extend([(ROOT / 'pykrita' / 'tfm.desktop', targets[1]),
                    (ROOT / 'actions' / 'tfm.action', targets[2])])
    if not all(source.is_file() for source, _ in sources):
        raise FileNotFoundError('Missing TFM program file')
    created = []
    created_dirs = []
    try:
        for source, target in sources:
            missing_dirs = []
            directory = target.parent
            while not directory.exists():
                missing_dirs.append(directory)
                directory = directory.parent
            for directory in reversed(missing_dirs):
                try:
                    directory.mkdir()
                    created_dirs.append(directory)
                except FileExistsError:
                    if not directory.is_dir():
                        raise
            with source.open('rb') as src, target.open('xb') as dst:
                created.append(target)
                shutil.copyfileobj(src, dst)
            if digest(source) != digest(target):
                raise IOError('File verification failed: ' + str(target))
    except Exception:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    return len(sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resource_directory', help='Existing isolated resource directory')
    args = parser.parse_args()
    print('Staged and verified %d program files.' % stage(args.resource_directory))
    print('Plugin activation and old-plugin switching are not performed.')


if __name__ == '__main__':
    main()
