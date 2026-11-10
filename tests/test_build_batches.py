import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tfm_build_artifacts', ROOT / 'build_artifacts.py')
artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifacts)


def publish(out, payload=b'first'):
    staged = out / ('pending-' + payload.decode())
    staged.mkdir(parents=True)
    for name in artifacts.BINARY_NAMES:
        (staged / name).write_bytes(payload + name.encode())
    return artifacts.publish_batch(out, staged, {'sources': {}, 'inputs': {'source.cpp': 'old'}})


def test_complete_batch_and_source_mismatch(tmp_path):
    batch = publish(tmp_path)
    with mock.patch.object(artifacts, 'source_inputs', return_value={'source.cpp': 'old'}):
        assert artifacts.validated_current(tmp_path, tmp_path)[0] == batch
    with mock.patch.object(artifacts, 'source_inputs', return_value={'source.cpp': 'new'}):
        with pytest.raises(ValueError, match='Source or generated'):
            artifacts.validated_current(tmp_path, tmp_path)


@pytest.mark.parametrize('name', artifacts.BINARY_NAMES)
def test_missing_or_tampered_binary_is_rejected(tmp_path, name):
    batch = publish(tmp_path)
    (tmp_path / 'bin' / name).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='modified build'):
        artifacts.validated_current(tmp_path, tmp_path, check_sources=False)
    (batch / name).unlink()
    with pytest.raises(ValueError, match='Missing or modified binary'):
        artifacts.validate_batch(batch)


def test_worker_failure_keeps_previous_batch(tmp_path):
    old = publish(tmp_path)
    pointer = (tmp_path / 'current.json').read_bytes()
    pending = tmp_path / 'failed'; pending.mkdir()
    (pending / 'kritatfm.dll').write_bytes(b'new dll')
    with pytest.raises(FileNotFoundError):
        artifacts.publish_batch(tmp_path, pending, {'sources': {}, 'inputs': {}})
    assert (tmp_path / 'current.json').read_bytes() == pointer
    assert artifacts.validated_current(tmp_path, tmp_path, check_sources=False)[0] == old


def test_interrupted_publication_rejected_and_prior_batch_recoverable(tmp_path):
    old = publish(tmp_path)
    replace = artifacts.os.replace

    def interrupt(source, target):
        if Path(target) == tmp_path / 'bin/tfm_vulkan_worker.exe':
            raise OSError('simulated power interruption')
        return replace(source, target)

    with mock.patch.object(artifacts.os, 'replace', side_effect=interrupt):
        with pytest.raises(OSError, match='interruption'):
            publish(tmp_path, b'second')
    assert json.loads((tmp_path / 'current.json').read_text())['batch_id'] == old.name
    assert artifacts.validate_batch(old)['batch_id'] == old.name
    with pytest.raises(ValueError, match='Interrupted or modified'):
        artifacts.validated_current(tmp_path, tmp_path, check_sources=False)


def test_manifest_tampering_rejected(tmp_path):
    batch = publish(tmp_path)
    path = batch / 'manifest.json'
    manifest = json.loads(path.read_text()); manifest['inputs'] = {}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='batch identity'):
        artifacts.validate_batch(batch)
