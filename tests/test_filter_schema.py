import hashlib
import importlib.util
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


def test_catalog_matches_pre_refactor_contract():
    catalog = runpy.run_path(str(ROOT / 'pykrita/tfm/filters/catalog.py'))
    value = {'filters': catalog['FILTERS'], 'defaults': catalog['FILTER_DEFAULT_SPECS']}
    actual = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    # Frozen from the untouched baseline catalog, not the schema generator.
    assert actual == 'a2379162c7fe4dc3b6c1e2ad2441170efec977a1e6cfbd889641d994008b8175'

