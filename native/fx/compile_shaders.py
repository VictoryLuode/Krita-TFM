"""Regenerate the embedded Vulkan 1.0 Motion shader with Khronos glslang."""
import argparse
import struct
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', required=True, help='Path to glslang or glslangValidator')
    parser.add_argument('--shader', default='motion.comp', help='Shader filename below shaders/')
    parser.add_argument('--symbol', default='kMotionSpv', help='C++ array symbol')
    parser.add_argument('--header', default='', help='Output header path, relative to native/fx')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    shader = root / 'shaders' / args.shader
    stem = Path(args.shader).stem
    target = root / (args.header or f'src/{stem}_spv.h')
    output = root.parents[1] / 'build/vulkan-tools' / f'{stem}.spv'
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.compiler, '-V', '--target-env', 'vulkan1.0', '-o', str(output), str(shader)], check=True)
    raw = output.read_bytes()
    words = struct.unpack('<' + 'I' * (len(raw) // 4), raw)
    lines = ['#pragma once', '#include <cstdint>', f'// Generated from shaders/{args.shader}; see compile_shaders.py.']
    lines += [f'static constexpr std::uint32_t {args.symbol}[] = {{']
    lines += ['    ' + ', '.join('0x%08xu' % w for w in words[i:i+8]) + ',' for i in range(0, len(words), 8)]
    lines += ['};', '']
    target.write_text('\n'.join(lines), encoding='utf-8')
    print('Generated', target.name, 'SPIR-V bytes', len(raw))


if __name__ == '__main__':
    main()
