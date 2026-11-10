"""Execute production C++ math and the actual worker/shader (no copied algorithms)."""
import colorsys
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / 'native/fx/src'
CASES = [(4, 80, 0, 1, .5, 1), (4, 80, 0, 0, .5, 1),
         (4, -60, 30, 1, 0, .7), (3, 5700, 0, 1, 1, 0),
         (3, 6500, 100, 1, 1, 0), (3, 11000, -80, .7, 0, 0)]
pytestmark = pytest.mark.native


@pytest.fixture(scope='module')
def probe(tmp_path_factory):
    compiler = os.environ.get('CXX') or shutil.which('clang++')
    if not compiler:
        pytest.skip('C++17 compiler unavailable; set CXX')
    out = tmp_path_factory.mktemp('pointwise')
    exe = out / ('probe.exe' if os.name == 'nt' else 'probe')
    subprocess.run([compiler, '-std=c++17', '-O2', '-I' + str(SRC),
                    str(Path(__file__).with_name('pointwise_probe.cpp')), '-o', str(exe)], check=True, timeout=90)
    return exe, out


def test_production_math(probe):
    subprocess.run([str(probe[0])], check=True, timeout=15)


def shader_bytes(header):
    words = [int(word, 16) for word in re.findall(r'0x([0-9a-f]+)u', header.read_text(encoding='utf-8'))]
    return struct.pack('<' + 'I'*len(words), *words)


def gpu(worker, shader, pixels, width, height):
    frames = []
    for case in CASES:
        op, *generic = case
        params = struct.pack('<13i21fi', op, width, height, *([0]*10),
                             *([0.0]*13), *generic, *([0.0]*3), 0)
        frames.append(b'TFMV' + struct.pack('<11I', 1, len(shader), len(pixels), len(params), len(pixels),
                                           (width+15)//16, (height+15)//16, 1, 0, 1, 2)
                      + shader + pixels + params)
    started = time.perf_counter()
    run = subprocess.run([str(worker)], input=b''.join(frames)+b'TFMV'+struct.pack('<I',2),
                         capture_output=True, timeout=60)
    assert run.returncode == 0, run.stderr.decode(errors='replace')
    data, pos = run.stdout, 0

    def take(count):
        nonlocal pos
        assert 0 <= count <= len(data)-pos, 'truncated worker response'
        value = data[pos:pos+count]; pos += count
        return value

    def u32():
        return struct.unpack('<I',take(4))[0]

    def string():
        return take(u32()).decode('utf-8',errors='replace')

    assert take(4) == b'TFMV' and u32() == 0
    ok, _float64 = u32(), u32()
    device, error = string(), string()
    assert ok, 'Vulkan unavailable: ' + error
    results = []
    for _ in CASES:
        assert take(4) == b'TFMV' and u32() == 3
        ok, name, error = u32(), string(), string()
        assert ok, error
        results.append(take(len(pixels)))
    assert pos == len(data), 'unexpected trailing protocol data'
    return results, device, time.perf_counter()-started


def test_actual_gpu_matches_cpu(probe):
    worker = Path(os.environ.get('TFM_TEST_WORKER', ROOT/'build/native-5.3/bin/tfm_vulkan_worker.exe'))
    if not worker.is_file():
        pytest.skip('built Vulkan worker required; run native/fx/build.py or set TFM_TEST_WORKER')
    exe, out = probe
    width, height = 256, 64
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            r,g,b = colorsys.hsv_to_rgb(x/width, (y%16)/15, .1+.9*(y//16)/3)
            pixels.extend((round(b*255),round(g*255),round(r*255),(x*13+y*17)%256))
    source = out / 'input.bgra'; source.write_bytes(pixels)
    shader = shader_bytes(SRC/'tfm_pointwise_spv.h')
    outputs, device, elapsed = gpu(worker,shader,pixels,width,height)
    reports = []
    artifact_dir = Path(os.environ.get('TFM_TEST_ARTIFACTS',ROOT/'build/test-results')) / 'pointwise-gpu'
    artifact_dir.mkdir(parents=True,exist_ok=True)
    (artifact_dir/'input.bgra').write_bytes(pixels)
    for index, (case, actual) in enumerate(zip(CASES,outputs)):
        expected_path = out / f'cpu-{index}.bgra'
        subprocess.run([str(exe),str(source),str(expected_path),*map(str,case)],check=True,timeout=15)
        expected = expected_path.read_bytes()
        differences = [abs(a-b) for a,b in zip(expected,actual)]
        assert actual[3::4] == pixels[3::4], 'GPU alpha changed'
        assert max(differences) <= 1, f'CPU/GPU mismatch case {case}: {max(differences)}'
        (artifact_dir/f'cpu-{index}.bgra').write_bytes(expected)
        (artifact_dir/f'gpu-{index}.bgra').write_bytes(actual)
        reports.append({'parameters':case,'max_byte_error':max(differences),
                        'different_bytes':sum(d!=0 for d in differences)})
    report = {'device':device,'width':width,'height':height,'shader_sha256':hashlib.sha256(shader).hexdigest(),
              'worker_sha256':hashlib.sha256(worker.read_bytes()).hexdigest(),
              'cold_process_six_dispatch_seconds':elapsed,'cases':reports}
    (artifact_dir/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
