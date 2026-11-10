"""Fault injection against actual Windows IPC, including send-side backpressure."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.native
def test_production_ipc_lifecycle(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows overlapped IPC test')
    compiler = os.environ.get('CXX') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++17 compiler unavailable; set CXX')
    root = Path(__file__).resolve().parents[3]
    source = root/'native/fx/src'
    test = Path(__file__).with_suffix('.cpp')
    stub = tmp_path/'stub.cpp'
    stub.write_text('extern "C" __declspec(dllexport) void fixture() {}', encoding='utf-8')
    subprocess.run([compiler,'-shared',str(stub),'-o',str(tmp_path/'kritatfm.dll')],check=True,timeout=60)
    exe = tmp_path/'test.exe'
    subprocess.run([compiler,'-std=c++17','-O2','-I'+str(source),str(test),
                    str(source/'tfm_vulkan.cpp'),'-o',str(exe)],check=True,timeout=90)
    shutil.copy2(exe,tmp_path/'tfm_vulkan_worker.exe')
    run = subprocess.run([str(exe),'--test'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    out = Path(os.environ.get('TFM_TEST_ARTIFACTS',root/'build/test-results'))/'vulkan-lifecycle'
    out.mkdir(parents=True,exist_ok=True)
    (out/'result.log').write_text(run.stdout+run.stderr,encoding='utf-8')
    assert run.returncode == 0, run.stdout+run.stderr
    (out/'provenance.json').write_text(json.dumps({
        'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                   (source/'tfm_vulkan.cpp',source/'tfm_vulkan.h',test)},
        'status':'passed'},indent=2),encoding='utf-8')
