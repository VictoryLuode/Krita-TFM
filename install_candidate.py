"""Stage TFM Python resources into an empty, isolated Krita resource directory.

This copies the resource-side packages (pykrita/tfm, pykrita/quick_image_search,
shared qtcompat, desktop file, actions, and tfm_color_range.dll). Native filter
binaries kritatfm.dll and tfm_vulkan_worker.exe must be installed separately into
the Krita install lib/kritaplugins/ folder, or packed with package_release.py.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
from build_artifacts import resource_inventory, validated_current, BINARY_NAMES

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def _package_files(package_dir, suffix_ok=('.py', '.html'), extra_files=()):
    extras = {Path(p) for p in extra_files}
    files = []
    for path in package_dir.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        if path.suffix in suffix_ok or path in extras:
            files.append(path)
    return files


def stage(destination, *, native_directory=None):
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

    tfm_dst = destination / 'pykrita' / 'tfm'
    search_dst = destination / 'pykrita' / 'quick_image_search'
    qtcompat_dst = destination / 'pykrita' / 'qtcompat.py'
    i18n_dst = destination / 'pykrita' / 'i18n.py'
    ui_chrome_dst = destination / 'pykrita' / 'ui_chrome.py'
    desktop_dst = destination / 'pykrita' / 'tfm.desktop'
    action_dst = destination / 'actions' / 'tfm.action'
    targets = [tfm_dst, search_dst, qtcompat_dst, i18n_dst, ui_chrome_dst, desktop_dst, action_dst,
               destination / "pykrita/tfm_diagnostics.py"]
    if any(path.exists() for path in targets):
        raise FileExistsError('TFM already exists in the destination; refusing to overwrite')

    batch = None
    if native_directory is not None:
        native_directory = Path(native_directory).resolve()
        if not native_directory.is_dir():
            raise ValueError('Native destination directory must already exist')
        batch, _manifest = validated_current(ROOT)
    sources = [(source, destination / relative) for source, relative in
               resource_inventory(ROOT, batch / 'tfm_color_range.dll' if batch else None)]
    if batch:
        sources.extend((batch / name, native_directory / name)
                       for name in BINARY_NAMES if name != 'tfm_color_range.dll')
    if any(target.exists() for _, target in sources):
        raise FileExistsError('Candidate destination contains program files; refusing to overwrite')
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
    parser.add_argument('--native-directory', type=Path, help='Empty isolated kritaplugins directory; verifies a full native batch')
    args = parser.parse_args()
    print('Staged and verified %d program files.' % stage(args.resource_directory, native_directory=args.native_directory))
    print('Plugin activation and old-plugin switching are not performed.')


if __name__ == '__main__':
    main()
