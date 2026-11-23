import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]


def test_generated_catalog_and_native_metadata_are_current():
    generator = runpy.run_path(str(ROOT / 'scripts/generate_filter_metadata.py'))
    assert generator['generate'](check=True) == []


def test_invalid_schema_is_rejected():
    generator = runpy.run_path(str(ROOT / 'scripts/generate_filter_metadata.py'))
    schema = json.loads((ROOT / 'schema/filters.json').read_text(encoding='utf-8'))
    schema['filters'][0]['settings'][0]['default'] = 99
    import pytest
    with pytest.raises(ValueError, match='outside range'):
        generator['outputs'](schema)


def test_persisted_filter_contract():
    schema = json.loads((ROOT / 'schema/filters.json').read_text(encoding='utf-8'))
    expected = json.loads(Path(__file__).with_name('filter_contract.json').read_text(encoding='utf-8'))
    fields = ('value_type', 'default', 'min', 'max', 'aliases')
    assert {entry['id'] for entry in schema['filters']} == set(expected)
    for entry in schema['filters']:
        actual = {}
        for setting in entry['settings']:
            contract = {k: setting[k] for k in fields if k in setting}
            if 'options' in setting:
                contract['options'] = [option[0] for option in setting['options']]
            actual[setting['key']] = contract
        assert actual == expected[entry['id']], entry['id']
