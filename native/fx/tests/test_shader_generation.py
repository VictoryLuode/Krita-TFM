"""Compile a real shader and reject an obsolete embedded binary."""
import importlib.util
from pathlib import Path

import pytest


def test_changed_shader_requires_regeneration(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('shader_generation', root / 'compile_shaders.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    try:
        compiler = generator.find_compiler()
    except FileNotFoundError as error:
        pytest.skip(str(error))
    shader = tmp_path / 'pointwise.comp'
    shader.write_bytes((root / 'shaders/pointwise.comp').read_bytes())
    header = tmp_path / 'pointwise.h'
    assert generator.compile_one(compiler, shader, 'kPointwiseSpv', header)
    assert not generator.compile_one(compiler, shader, 'kPointwiseSpv', header, check=True)
    import re
    changed, count = re.subn(r'(void\s+main\s*\(\s*\)\s*\{)', r'\1\n return;', shader.read_text(), count=1)
    assert count == 1
    shader.write_text(changed)
    with pytest.raises(ValueError, match='Stale generated shader'):
        generator.compile_one(compiler, shader, 'kPointwiseSpv', header, check=True)
    assert generator.compile_one(compiler, shader, 'kPointwiseSpv', header)
    assert not generator.compile_one(compiler, shader, 'kPointwiseSpv', header, check=True)
