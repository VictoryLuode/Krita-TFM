"""Regenerate the embedded Vulkan 1.0 Motion shader with Khronos glslang."""
import argparse
import struct
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', required=True, help='Path to glslang or glslangValidator')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    shader = root / 'shaders/motion.comp'
    target = root / 'src/tfm_motion_spv.h'
    output = root.parents[1] / 'build/vulkan-tools/motion.spv'
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.compiler, '-V', '--target-env', 'vulkan1.0', '-o', str(output), str(shader)], check=True)
    raw = output.read_bytes()
    words = struct.unpack('<' + 'I' * (len(raw) // 4), raw)
    lines = ['#pragma once', '#include <cstdint>', '// Generated from shaders/motion.comp; see compile_shaders.py.']
    lines += ['static constexpr std::uint32_t kMotionSpv[] = {']
    lines += ['    ' + ', '.join('0x%08xu' % w for w in words[i:i+8]) + ',' for i in range(0, len(words), 8)]
    lines += ['};', '']
    target.write_text('\n'.join(lines), encoding='utf-8')
    print('Generated', target.name, 'SPIR-V bytes', len(raw))


if __name__ == '__main__':
    main()
