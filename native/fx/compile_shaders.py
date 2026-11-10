"""Regenerate the embedded Vulkan 1.0 Motion shader with Khronos glslang."""
import argparse
import struct
import shutil
import os
import tempfile
import subprocess
from pathlib import Path


SHADERS = {
    'motion': 'Motion', 'pointwise': 'Pointwise', 'lens': 'Lens',
    'bloom_legacy': 'BloomLegacy', 'guided_lut': 'GuidedLut',
    'kuwahara': 'Kuwahara', 'halation': 'Halation', 'flare': 'Flare',
}
ROOT = Path(__file__).resolve().parent


def find_compiler():
    configured = os.environ.get('GLSLANG')
    found = configured or shutil.which('glslang') or shutil.which('glslangValidator')
    if found:
        return str(found)
    for base in (Path('D:/Scoop/apps/glslang'), Path.home() / 'scoop/apps/glslang'):
        candidates = sorted(base.glob('*/bin/glslang.exe'), reverse=True)
        if candidates:
            return str(candidates[0])
    raise FileNotFoundError('Set GLSLANG or install glslang/glslangValidator')


def compile_one(compiler, shader, symbol, target, check=False):
    with tempfile.TemporaryDirectory(prefix='tfm-shader-') as temporary:
        output = Path(temporary) / 'shader.spv'
        subprocess.run([str(compiler), '-V', '--target-env', 'vulkan1.0', '-o', str(output), str(shader)],
                       check=True, capture_output=True, timeout=60)
        raw = output.read_bytes()
    words = struct.unpack('<' + 'I' * (len(raw) // 4), raw)
    lines = ['#pragma once', '#include <cstdint>', f'// Generated from shaders/{shader.name}; see compile_shaders.py.']
    lines += [f'static constexpr std::uint32_t {symbol}[] = {{']
    lines += ['    ' + ', '.join('0x%08xu' % w for w in words[i:i+8]) + ',' for i in range(0, len(words), 8)]
    lines += ['};', '']
    content = '\n'.join(lines)
    if target.is_file() and target.read_text(encoding='utf-8') == content:
        return False
    if check:
        raise ValueError('Stale generated shader: ' + target.name)
    target.write_text(content, encoding='utf-8', newline='\n')
    return True


def generate_all(compiler=None, check=False):
    compiler = compiler or find_compiler()
    return [stem for stem, symbol in SHADERS.items()
            if compile_one(compiler, ROOT / 'shaders' / (stem + '.comp'), 'k' + symbol + 'Spv',
                           ROOT / 'src' / ('tfm_' + stem + '_spv.h'), check)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--shader', default='motion.comp')
    parser.add_argument('--symbol', default='kMotionSpv')
    parser.add_argument('--header', default='')
    args = parser.parse_args()
    compiler = args.compiler or find_compiler()
    if args.all:
        print('Shaders:', generate_all(compiler, args.check) or 'current')
    else:
        stem = Path(args.shader).stem
        target = ROOT / (args.header or f'src/tfm_{stem}_spv.h')
        compile_one(compiler, ROOT / 'shaders' / args.shader, args.symbol, target, args.check)


if __name__ == '__main__':
    main()
