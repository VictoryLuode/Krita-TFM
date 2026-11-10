"""Build production colour-match sources in an isolated directory, then test them.

Usage: python tests/run_statistical_regions_native.py --build BUILD --deps DEPS
       --runtime KRITA_INSTALL --out SCRATCH_DIRECTORY
The configured build supplies read-only compiler flags and import libraries.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess


def split(command):
    shell = ctypes.windll.shell32
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    count = ctypes.c_int()
    pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
    try:
        return [pointer[i] for i in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(pointer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'deps', 'runtime', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = options.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    entries = json.loads((options.build/'compile_commands.json').read_text())
    entry = next(e for e in entries if e['file'].endswith('tfm_clipboard_color_match.cpp'))
    flags = entry.get('arguments') or split(entry['command'])
    compiler = flags[0]
    flags = flags[1:flags.index('-o')]
    flags.insert(0, '-I'+str(root/'src'))
    env = os.environ.copy()
    host_bin = Path(entry['directory'])/'bin'
    env['PATH'] = ';'.join([str(host_bin), str(options.deps/'bin'), str(options.runtime/'bin'), str(Path(compiler).parent), env['PATH']])
    env['QT_PLUGIN_PATH'] = str(options.runtime/'plugins')
    env['QT_QPA_PLATFORM'] = 'windows'
    env['TFM_KRITA_RUNTIME'] = str(options.runtime)
    env['FXMANAGER_KRITA_RUNTIME'] = str(options.runtime)

    def run(args, label):
        result = subprocess.run(args, cwd=entry['directory'], env=env, capture_output=True, text=True, errors='replace', timeout=60)
        (out/(label+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        if result.returncode or label == 'result':
            print(result.stdout+result.stderr, flush=True)
        print(label, 'EXIT', result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)

    sources = [root/'src/tfm_clipboard_color_match.cpp', root/'src/tfm_drag_spinbox.cpp', root/'tests/test_statistical_regions_native.cpp']
    for stem in ('tfm_clipboard_color_match_widget', 'tfm_drag_spinbox'):
        moc = out/('moc_'+stem+'.cpp')
        run([str(options.deps/'bin/moc.exe'), str(root/'src'/(stem+'.h')), '-o', str(moc)], 'moc_'+stem)
        sources.append(moc)
    objects = []
    for source in sources:
        obj = out/(source.stem+'.obj')
        run([compiler, *flags, '-o', str(obj), '-c', str(source)], source.stem)
        objects.append(str(obj))
    link = split((options.build/'link.rsp').read_text())
    # Keep library arguments only; no shared objects or output files are modified.
    libraries = [a for a in link if a.endswith(('.a', '.lib')) or a.startswith('-l')]
    executable = out/'regions.exe'
    run([compiler, *objects, *libraries, '-o', str(executable)], 'link')
    run([str(executable)], 'result')


if __name__ == '__main__':
    main()
