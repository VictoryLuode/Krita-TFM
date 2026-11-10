"""Compile production Bloom with read-only build flags, in a separate output dir.

Usage: python tests/run_bloom_device_native.py --build BUILD --deps DEPS
       --runtime KRITA_INSTALL --out SCRATCH --compiler CLANGXX
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
from run_statistical_regions_native import split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('build', 'deps', 'runtime', 'out', 'compiler'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--baseline', action='store_true', help='Build a temporary copy with the former current-device read')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    flags = split('compiler '+(args.build/'obj/tfm_bloom.cpp.rsp').read_text())[1:]
    flags = flags[:flags.index('-o')]
    flags.insert(0, '-I'+str(root/'src'))
    host = Path(json.loads((args.build/'compile_commands.json').read_text())[0]['directory'])
    env = os.environ.copy()
    env['PATH'] = ';'.join([str(host/'bin'), str(args.deps/'bin'), str(args.runtime/'bin'), str(args.compiler.parent), env['PATH']])
    env['QT_PLUGIN_PATH'] = str(args.runtime/'plugins')
    env['QT_QPA_PLATFORM'] = 'windows'
    env['TFM_KRITA_RUNTIME'] = str(args.runtime)
    env['FXMANAGER_KRITA_RUNTIME'] = str(args.runtime)

    def run(command, label):
        result = subprocess.run([str(x) for x in command], cwd=host, env=env, capture_output=True, text=True, errors='replace', timeout=60)
        (out/(label+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        if result.returncode or label == 'result':
            print(result.stdout+result.stderr, flush=True)
        print(label, 'EXIT', result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)

    bloom = root/'src/tfm_bloom.cpp'
    if args.baseline:
        text = bloom.read_text()
        start = text.index('    // Neighbouring chunks')
        end = text.index('    if(source.isNull())', start)
        text = text[:start]+'    const QImage source=tfm::readImage(d,read);\n'+text[end:]
        bloom = out/'baseline_bloom.cpp'
        bloom.write_text(text)
    sources = [bloom, root/'src/tfm_processing.cpp', root/'src/tfm_filter_widget.cpp', root/'src/tfm_drag_spinbox.cpp', root/'tests/test_bloom_device_native.cpp']
    for stem in ('tfm_filter_widget', 'tfm_drag_spinbox'):
        moc = out/('moc_'+stem+'.cpp')
        run([args.deps/'bin/moc.exe', root/'src'/(stem+'.h'), '-o', moc], 'moc_'+stem)
        sources.append(moc)
    objects = []
    for source in sources:
        obj = out/(source.stem+'.obj')
        run([args.compiler, *flags, '-o', obj, '-c', source], source.stem)
        objects.append(obj)
    link = split('compiler '+(args.build/'link.rsp').read_text())[1:]
    libraries = [a for a in link if a.endswith(('.a', '.lib')) or a.startswith('-l')]
    exe = out/'bloom-device.exe'
    run([args.compiler, *objects, *libraries, '-o', exe], 'link')
    run([exe], 'result')


if __name__ == '__main__':
    main()
