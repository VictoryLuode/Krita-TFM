"""Compile the actual pointwise filters and run them on real Krita paint devices.

Requires a configured native build (compiler flags/import libraries), not a live
Krita process. All outputs and settings stay in --out; the installation is read-only.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import tempfile

from run_statistical_regions_native import split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'deps', 'runtime', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--test-suite', choices=('pointwise','spatial'), default='pointwise')
    parser.add_argument('--source-root', type=Path, help='Explicit preserved production source snapshot for baseline recording')
    parser.add_argument('--run-only', action='store_true')
    parser.add_argument('--record-baseline', action='store_true')
    args = parser.parse_args()
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    root = Path(__file__).resolve().parents[1]
    source_root = args.source_root.resolve() if args.source_root else root / 'src'
    if args.source_root and not args.record_baseline:
        parser.error('--source-root is only allowed for baseline recording')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    entries = json.loads((args.build / 'compile_commands.json').read_text(encoding='utf-8'))
    entry = next(e for e in entries if e['file'].endswith('fxmanager_vibrance.cpp'))
    command = entry.get('arguments') or split(entry['command'])
    compiler = command[0]
    flags = ['-I' + str(source_root), *command[1:command.index('-o')]]
    if args.record_baseline:
        flags.append('-DTFM_RECORD_BASELINE')
    runtime = args.runtime.resolve()
    env = dict(os.environ, QT_PLUGIN_PATH=str(runtime / 'bin'), QT_QPA_PLATFORM='offscreen',
               FXMANAGER_KRITA_RUNTIME=str(runtime), KRITA_PLUGIN_PATH=str(runtime / 'lib/kritaplugins'), TFM_THREADS='2', TFM_VULKAN_DISABLE='1')
    env['PATH'] = os.pathsep.join([str(runtime / 'bin'), str(Path(entry['directory']) / 'bin'),
                                  str(args.deps.resolve() / 'bin'), str(Path(compiler).parent), env['PATH']])

    def run(command, label):
        with (out / (label + '.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run([str(x) for x in command], cwd=entry['directory'], env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=120)
        output = (out / (label + '.log')).read_text(encoding='utf-8', errors='replace')
        if result.returncode or label == 'result':
            print(output, flush=True)
        print(label, 'EXIT', result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(1)

    exe = out / (args.test_suite + '-native.exe')
    if not args.run_only:
        stems = ('fxmanager_vibrance', 'fxmanager_color_temperature', 'fxmanager_processing',
                 'fxmanager_film_grain', 'fxmanager_vignette', 'fxmanager_vignette_widget',
                 'fxmanager_filter_widget', 'fxmanager_drag_spinbox', 'tfm_pointwise_gpu', 'fxmanager_vulkan')
        widgets=['fxmanager_filter_widget','fxmanager_drag_spinbox','fxmanager_vignette_widget']
        if args.test_suite=='spatial':
            stems += ('fxmanager_bloom','fxmanager_halation','fxmanager_kuwahara','fxmanager_flare',
                      'fxmanager_lens_distortion','fxmanager_lens_distortion_widget',
                      'fxmanager_color_range_mask','fxmanager_color_range_mask_widget',
                      'tfm_bloom_gpu','tfm_halation_gpu','tfm_kuwahara_gpu','tfm_flare_gpu','tfm_lens_gpu')
            widgets += ['fxmanager_lens_distortion_widget','fxmanager_color_range_mask_widget']
        sources = [source_root / (stem + '.cpp') for stem in stems]
        for stem in widgets:
            moc = out / ('moc_' + stem + '.cpp')
            run([args.deps.resolve() / 'bin/moc.exe', source_root / (stem + '.h'), '-o', moc], 'moc_' + stem)
            sources.append(moc)
        sources.append(root / ('tests/test_' + args.test_suite + '_native.cpp'))
        objects = []
        for source in sources:
            obj = out / (source.stem + '.obj')
            run([compiler, *flags, '-o', obj, '-c', source], source.stem)
            objects.append(obj)
        link = split('compiler ' + (args.build / 'link.rsp').read_text(encoding='utf-8'))[1:]
        libraries = [arg for arg in link if arg.endswith(('.a', '.lib')) or arg.startswith('-l')]
        exe = out / (args.test_suite + '-native.exe')
        run([compiler, *objects, *libraries, '-o', exe], 'link')
    with tempfile.TemporaryDirectory(prefix='tfm-native-profile-') as profile:
        resource=Path(profile)/'resource'; resource.mkdir()
        (Path(profile)/'kritarc').write_text('ResourceDirectory='+resource.as_posix()+'\n',encoding='utf-8')
        env.update(KLOCALAPPDATA=profile, LOCALAPPDATA=profile, APPDATA=profile)
        run([exe, out, 'baseline' if args.record_baseline else 'verify'], 'result')


if __name__ == '__main__':
    main()
