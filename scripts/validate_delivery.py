"""Verify full staging/rollback and the delivered ZIP without launching Krita."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install_candidate
from build_artifacts import digest, resource_inventory, validated_current, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    batch, manifest = validated_current(ROOT)
    with tempfile.TemporaryDirectory(prefix='delivery-', dir=ROOT / 'build') as temporary:
        base = Path(temporary)
        resource, native = base / 'resource', base / 'native'
        resource.mkdir(); native.mkdir()
        sentinel = resource / 'unrelated-user-data.txt'
        sentinel.write_bytes(b'preserve')
        original_digest = install_candidate.digest

        def fail_at_worker(path):
            if Path(path) == native / 'tfm_vulkan_worker.exe':
                raise OSError('injected last-native-file verification failure')
            return original_digest(path)

        with mock.patch.object(install_candidate, 'digest', side_effect=fail_at_worker):
            try:
                install_candidate.stage(resource, native_directory=native)
            except OSError as error:
                assert 'injected' in str(error)
            else:
                raise AssertionError('failure injection did not execute')
        assert list(resource.rglob('*')) == [sentinel]
        assert not list(native.iterdir())
        assert sentinel.read_bytes() == b'preserve'
        installed = install_candidate.stage(resource, native_directory=native)
        for source, relative in resource_inventory(ROOT, batch / 'tfm_color_range.dll'):
            assert digest(source) == digest(resource / relative)
        for name in ('kritatfm.dll', 'tfm_vulkan_worker.exe'):
            assert digest(native / name) == manifest['binaries'][name]
        try:
            install_candidate.stage(resource, native_directory=native)
        except FileExistsError:
            pass
        else:
            raise AssertionError('existing candidate was overwritten')
    with zipfile.ZipFile(args.package) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
                   and ':' not in name and '\\' not in name for name in names)
        prefixes = {name.split('/')[0] for name in names}
        assert len(prefixes) == 1
        prefix = prefixes.pop() + '/'
        inventory = json.loads(archive.read(prefix + 'PACKAGE-MANIFEST.json'))
        assert inventory['batch_id'] == manifest['batch_id']
        assert set(names) == {prefix + name for name in inventory['files']} | {prefix + 'PACKAGE-MANIFEST.json'}
        for name, expected in inventory['files'].items():
            content = archive.read(prefix + name)
            assert hashlib.sha256(content).hexdigest() == expected, name
            # Detect embedded developer-machine paths, including UTF-16 literals.
            for value in (content, content.replace(b'\x00', b'')):
                assert not re.search(rb'[CDE]:[/\\](?:Users|Dev|Config|Scoop)[/\\]', value, re.I), name
        assert json.loads(archive.read(prefix + 'BUILD-MANIFEST.json')) == manifest
        assert json.loads(archive.read(prefix + 'VALIDATION.json'))['batch_id'] == manifest['batch_id']
        assert not any('/__pycache__/' in name or '/tests/' in name or '/build/' in name for name in names)
    result = {'schema_version': 1, 'batch_id': manifest['batch_id'], 'status': 'passed',
              'installed_files': installed, 'package_files': len(names),
              'package': args.package.name, 'sha256': digest(args.package),
              'checks': ['full candidate staging and hash verification',
                         'rollback after final native write preserves unrelated user file',
                         'existing candidate overwrite rejected', 'all ZIP paths and hashes verified',
                         'no embedded developer-machine paths', 'matching build and validation batch']}
    write_json(ROOT / 'build/candidate-evidence/delivery-validation.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
