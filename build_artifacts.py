"""Shared build provenance and distribution inventory (no host mutations)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

SCHEMA_VERSION = 2
BINARY_NAMES = ('kritatfm.dll', 'tfm_vulkan_worker.exe', 'tfm_color_range.dll')
SHARED_MODULES = ('qtcompat.py', 'i18n.py', 'ui_chrome.py', 'tfm_diagnostics.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def source_inputs(root):
    root = Path(root)
    paths = set()
    paths.update(source for source, _relative in license_inventory(root))
    for directory in ('native/fx/src', 'native/fx/shaders', 'native/fx/third_party', 'pykrita/tfm',
                      'pykrita/quick_image_search', 'schema', 'actions'):
        for path in (root / directory).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and (directory == 'native/fx/third_party' or path.suffix.lower() in {
                    '.c', '.cpp', '.h', '.hpp', '.inl', '.cmake', '.txt', '.comp', '.json',
                    '.qrc', '.ui', '.py', '.html', '.action'}):
                paths.add(path)
    for name in ('native/color_range.c', 'native/fx/build.py', 'native/fx/compile_shaders.py',
                 'native/fx/CMakeLists.txt', 'native/fx/inference/CMakeLists.txt',
                 'scripts/generate_filter_metadata.py', 'build_artifacts.py',
                 'install_candidate.py', 'package_release.py',
                 'pykrita/tfm.desktop', *('pykrita/' + name for name in SHARED_MODULES)):
        path = root / name
        if not path.is_file():
            raise FileNotFoundError('Missing build input: ' + name)
        paths.add(path)
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


def batch_id(manifest):
    content = {k: v for k, v in manifest.items() if k != 'batch_id'}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_batch(batch):
    batch = Path(batch)
    manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != SCHEMA_VERSION or manifest.get('batch_id') != batch_id(manifest):
        raise ValueError('Invalid build manifest or batch identity')
    if set(manifest.get('binaries', {})) != set(BINARY_NAMES):
        raise ValueError('Incomplete native batch')
    for name, expected in manifest['binaries'].items():
        if not (batch / name).is_file() or digest(batch / name) != expected:
            raise ValueError('Missing or modified binary: ' + name)
    return manifest


def publish_batch(out, staged, manifest):
    """Commit a complete immutable batch; current.json is the final commit record.

    bin/ and manifest.json remain compatibility mirrors. An interrupted mirror
    update fails validation; the prior current.json still locates a full rollback.
    """
    out, staged = Path(out), Path(staged)
    manifest = dict(manifest, schema_version=SCHEMA_VERSION)
    manifest['binaries'] = {name: digest(staged / name) for name in BINARY_NAMES}
    manifest['sha256'] = manifest['binaries']['kritatfm.dll']
    manifest['worker_sha256'] = manifest['binaries']['tfm_vulkan_worker.exe']
    manifest['dll'], manifest['worker'] = 'bin/kritatfm.dll', 'bin/tfm_vulkan_worker.exe'
    manifest['batch_id'] = batch_id(manifest)
    write_json(staged / 'manifest.json', manifest)
    validate_batch(staged)
    batch = out / 'batches' / manifest['batch_id']
    batch.parent.mkdir(parents=True, exist_ok=True)
    if not batch.exists():
        os.replace(staged, batch)
    else:
        validate_batch(batch)
    (out / 'bin').mkdir(exist_ok=True)
    for name in BINARY_NAMES:
        temporary = out / 'bin' / (name + '.pending')
        shutil.copy2(batch / name, temporary)
        os.replace(temporary, out / 'bin' / name)
    write_json(out / 'manifest.json', manifest)
    write_json(out / 'current.json', {'schema_version': SCHEMA_VERSION, 'batch_id': manifest['batch_id']})
    return batch


def validated_current(root, out=None, *, check_sources=True):
    root = Path(root)
    out = Path(out) if out is not None else root / 'build/native-5.3'
    pointer = json.loads((out / 'current.json').read_text(encoding='utf-8'))
    identifier = pointer.get('batch_id', '')
    if len(identifier) != 64 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Invalid current batch pointer')
    batch = out / 'batches' / identifier
    manifest = validate_batch(batch)
    if manifest['batch_id'] != identifier:
        raise ValueError('Batch pointer mismatch')
    if json.loads((out / 'manifest.json').read_text(encoding='utf-8')) != manifest:
        raise ValueError('Interrupted build publication: manifest mirror differs')
    for name, expected in manifest['binaries'].items():
        if not (out / 'bin' / name).is_file() or digest(out / 'bin' / name) != expected:
            raise ValueError('Interrupted or modified build publication: ' + name)
    if check_sources and source_inputs(root) != manifest['inputs']:
        raise ValueError('Source or generated files changed; rebuild before packaging/installing')
    return batch, manifest


def resource_inventory(root, color_range=None):
    """Single allowlist used by staging, deployment and packaging."""
    root = Path(root)
    required = ('pykrita/tfm/__init__.py', 'pykrita/tfm/manager.py',
                'pykrita/quick_image_search/__init__.py', 'pykrita/quick_image_search/docker.py',
                'pykrita/tfm.desktop', 'actions/tfm.action', *('pykrita/' + n for n in SHARED_MODULES))
    for name in required:
        if not (root / name).is_file():
            raise FileNotFoundError('Missing required TFM file: ' + name)
    result = []
    for package in ('tfm', 'quick_image_search'):
        for source in sorted((root / 'pykrita' / package).rglob('*')):
            if source.is_file() and '__pycache__' not in source.parts and source.suffix in ('.py', '.html'):
                result.append((source, source.relative_to(root).as_posix()))
    result.extend((root / name, name) for name in required if not name.endswith(('/__init__.py', '/manager.py', '/docker.py')))
    binary = Path(color_range) if color_range else root / 'pykrita/tfm/native/tfm_color_range.dll'
    if not binary.is_file():
        raise FileNotFoundError('Missing required TFM file: tfm/native/tfm_color_range.dll')
    result.append((binary, 'pykrita/tfm/native/tfm_color_range.dll'))
    result.extend((source, 'TFM/' + relative) for source, relative in license_inventory(root))
    return sorted(result, key=lambda pair: pair[1])


def license_inventory(root):
    root = Path(root)
    names = {
        'GPL-3.0.txt': 'LICENSE',
        'visioncpp.txt': 'native/fx/third_party/visioncpp/VISIONCPP_LICENSE',
        'ggml.txt': 'native/fx/third_party/visioncpp/LLAMA_LICENSE',
        'stb.txt': 'native/fx/third_party/visioncpp/depend/stb/STB_LICENSE',
        'vulkan-headers.md': 'native/fx/third_party/vulkan-headers/LICENSE.md',
        'Apache-2.0.txt': 'native/fx/third_party/vulkan-headers/LICENSES/Apache-2.0.txt',
        'MIT.txt': 'native/fx/third_party/vulkan-headers/LICENSES/MIT.txt',
    }
    return [(root / source, 'licenses/' + name) for name, source in names.items()]
