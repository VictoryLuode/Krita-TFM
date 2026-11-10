"""Real Qt5/Krita paint-device tests; never silently substitute mocked devices."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.native
def test_production_pointwise_devices():
    root = Path(__file__).resolve().parents[3]
    runtime = os.environ.get('KRITA_ROOT')
    if not runtime:
        pytest.skip('KRITA_ROOT required for the real paint-device tests')
    build = root / 'build/native-5.3'
    if not (build/'compile_commands.json').is_file():
        pytest.skip('configured native build required; run native/fx/build.py')
    out = Path(os.environ.get('TFM_TEST_ARTIFACTS',root/'build/test-results'))/'pointwise-device'
    subprocess.run([sys.executable,str(Path(__file__).with_name('run_pointwise_native.py')),
                    '--build',str(build),'--deps',str(root/'deps'),'--runtime',runtime,'--out',str(out)],
                   check=True,timeout=240)


@pytest.mark.native
@pytest.mark.parametrize('name',('spatial','bloom_device','filter_defaults','statistical_regions','transfer','blur','parallel_rows','backend_policy','profile'))
def test_built_production_regression(name):
    root = Path(__file__).resolve().parents[3]
    runtime = os.environ.get('KRITA_ROOT')
    if not runtime:
        pytest.skip('KRITA_ROOT required for real native regressions')
    build = root/'build/native-5.3'
    if not (build/'manifest.json').is_file():
        pytest.skip('built production objects and manifest required; run native/fx/build.py')
    out = Path(os.environ.get('TFM_TEST_ARTIFACTS',root/'build/test-results'))/name
    subprocess.run([sys.executable,str(Path(__file__).with_name('run_built_native.py')),
                    '--build',str(build),'--deps',str(root/'deps'),'--runtime',runtime,'--out',str(out),
                    '--test',str(Path(__file__).with_name('test_'+name+'_native.cpp'))],
                   check=True,timeout=240)


@pytest.mark.native
def test_actual_background_inference():
    root = Path(__file__).resolve().parents[3]
    runtime, model = os.environ.get('KRITA_ROOT'), os.environ.get('TFM_TEST_MODEL')
    if not runtime or not model:
        pytest.skip('KRITA_ROOT and TFM_TEST_MODEL required for actual AI inference')
    if not Path(model).is_file():
        pytest.fail('TFM_TEST_MODEL does not exist: '+model)
    out = Path(os.environ.get('TFM_TEST_ARTIFACTS',root/'build/test-results'))/'background-inference'
    subprocess.run([sys.executable,str(Path(__file__).with_name('run_built_native.py')),
                    '--build',str(root/'build/native-5.3'),'--deps',str(root/'deps'),
                    '--runtime',runtime,'--out',str(out),'--model',model,
                    '--test',str(Path(__file__).with_name('test_background_inference_native.cpp'))],
                   check=True,timeout=240)
