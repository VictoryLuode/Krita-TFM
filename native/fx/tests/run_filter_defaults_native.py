"""Compile and run the production native filter defaults against isolated settings.

Usage: python tests/run_filter_defaults_native.py --build BUILD --deps DEPS
       --runtime KRITA_INSTALL --out SCRATCH --compiler CLANGXX
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
from run_native_util import split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('build', 'deps', 'runtime', 'out', 'compiler'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    build = args.build.resolve()
    deps = args.deps.resolve()
    runtime = args.runtime.resolve()
    compiler = args.compiler.resolve()
    host = Path(json.loads((build / 'compile_commands.json').read_text())[0]['directory'])
    env = os.environ.copy()
    env['PATH'] = ';'.join([str(host / 'bin'), str(deps / 'bin'), str(runtime / 'bin'), str(compiler.parent), env['PATH']])
    env['QT_PLUGIN_PATH'] = str(runtime / 'plugins')
    env['QT_QPA_PLATFORM'] = 'windows'
    env['TFM_KRITA_RUNTIME'] = str(runtime)
    env['FXMANAGER_KRITA_RUNTIME'] = str(runtime)
    env['KLOCALAPPDATA'] = str(out / 'KLocalAppData')
    env['LOCALAPPDATA'] = str(out / 'LocalAppData-unused')
    Path(env['KLOCALAPPDATA']).mkdir(parents=True, exist_ok=True)

    def run(command, label):
        result = subprocess.run([str(x) for x in command], cwd=host, env=env,
                                capture_output=True, text=True, errors='replace', timeout=120)
        (out / (label + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode or label == 'result':
            print(result.stdout + result.stderr, flush=True)
        print(label, 'EXIT', result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)

    stems = ['tfm_processing', 'tfm_bloom', 'tfm_film_grain',
             'tfm_lens_distortion', 'tfm_lens_distortion_widget',
             'tfm_vignette', 'tfm_vignette_widget', 'tfm_color_range_mask',
             'tfm_color_range_mask_widget', 'tfm_guided_color_match_filter',
             'tfm_background_removal', 'tfm_birefnet', 'tfm_filter_widget',
             'tfm_drag_spinbox']
    objects = []
    for stem in stems:
        source = root / 'src' / (stem + '.cpp')
        flags = split('compiler ' + (build / 'obj' / (stem + '.cpp.rsp')).read_text())[1:]
        flags = flags[:flags.index('-o')]
        flags.insert(0, '-I' + str(root / 'src'))
        obj = out / (stem + '.obj')
        run([compiler, *flags, '-o', obj, '-c', source], 'compile_' + stem)
        objects.append(obj)
    test = root / 'tests/test_filter_defaults_native.cpp'
    flags = split('compiler ' + (build / 'obj/tfm_bloom.cpp.rsp').read_text())[1:]
    flags = flags[:flags.index('-o')]
    flags.insert(0, '-I' + str(root / 'src'))
    obj = out / 'test_filter_defaults_native.obj'
    run([compiler, *flags, '-o', obj, '-c', test], 'compile_test')
    objects.append(obj)
    headers = ['tfm_filter_widget', 'tfm_drag_spinbox', 'tfm_lens_distortion_widget',
               'tfm_vignette_widget', 'tfm_color_range_mask_widget']
    for stem in headers:
        moc_obj = out / ('moc_' + stem + '.obj')
        moc_cpp = out / ('moc_' + stem + '.cpp')
        run([deps / 'bin/moc.exe', root / 'src' / (stem + '.h'), '-o', moc_cpp], 'moc_' + stem)
        flags = split('compiler ' + (build / 'obj/tfm_bloom.cpp.rsp').read_text())[1:]
        flags = flags[:flags.index('-o')]
        flags.insert(0, '-I' + str(root / 'src'))
        run([compiler, *flags, '-o', moc_obj, '-c', moc_cpp], 'compile_moc_' + stem)
        objects.append(moc_obj)
    link = split('compiler ' + (build / 'link.rsp').read_text())[1:]
    libraries = [arg for arg in link if arg.endswith(('.a', '.lib')) or arg.startswith('-l')]
    exe = out / 'filter-defaults-native.exe'
    run([compiler, *objects, *libraries, '-o', exe], 'link')
    run([exe], 'result')


if __name__ == '__main__':
    main()
