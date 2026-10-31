"""Build kritatfm.dll (Krita 5.3.4.1 / Qt5) from the configured host graph.

Reuses the compile flags and static third-party libraries of the reference
kritafiltermanager target in Krita-Master-5.3.4.1/build-fxm-5.3; only the
TFM sources under native/fx/src are recompiled.  Output: Krita-TFM/build/native-5.3.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent          # Krita-TFM/native/fx
REPO = PROJECT.parents[1]                          # Krita-TFM
WORKSPACE = REPO.parent
HOST = WORKSPACE / 'Krita-Master-5.3.4.1/build-fxm-5.3'
STAGE = REPO / 'build' / 'native-5.3' / 'stage'
OUT = REPO / 'build' / 'native-5.3'
DEPS = WORKSPACE / 'deps'
def _find_compiler():
    if os.environ.get('CXX'):
        return Path(os.environ['CXX'])
    found = shutil.which('clang++')
    if found:
        return Path(found)
    for drive in (Path('D:/'), Path('C:/')):
        candidate = drive / 'Scoop/apps/llvm-mingw/current/bin/clang++.exe'
        if candidate.is_file():
            return candidate
    return Path('clang++.exe')


COMPILER = _find_compiler()


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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def escape(path):
    return str(path).replace('\\', '/').replace('$', '$$').replace(':', '$:').replace(' ', '$ ')


def main():
    env = os.environ.copy()
    extra_paths = [str(COMPILER.parent), str(DEPS / 'bin'), str(Path.home() / '.local/bin')]
    env['PATH'] = ';'.join(extra_paths) + ';' + env['PATH']
    env['PKG_CONFIG_PATH'] = str(DEPS / 'lib/pkgconfig')
    ninja = shutil.which('ninja', path=env['PATH'])
    cmake = shutil.which('cmake', path=env['PATH'])
    if not ninja or not cmake or not COMPILER.is_file():
        raise SystemExit('Need Scoop LLVM-MinGW, ninja, and cmake (uv tool or Scoop)')
    for args in ([cmake, '--version'], [ninja, '--version'], [str(COMPILER), '--version']):
        subprocess.run(args, env=env, check=True)
    cache = (HOST / 'CMakeCache.txt').read_text()
    if 'BUILD_WITH_QT6:BOOL=OFF' not in cache:
        raise SystemExit('Reference graph must use Qt5')
    files = sorted(p for p in (PROJECT / 'src').iterdir() if p.is_file() and
                   (p.suffix in {'.cpp', '.h', '.json', '.qrc', '.ui'} or p.name == 'CMakeLists.txt'))
    before = {p.name: digest(p) for p in files}
    STAGE.mkdir(parents=True, exist_ok=True)
    for p in files:
        target = STAGE / p.name
        if not target.is_file() or digest(target) != before[p.name]:
            shutil.copy2(p, target)
    OUT.mkdir(parents=True, exist_ok=True)
    auto = OUT / 'autogen'
    auto.mkdir(exist_ok=True)
    info = json.loads((HOST / 'plugins/filters/filtermanager/CMakeFiles/kritafiltermanager_autogen.dir/AutogenInfo.json').read_text())
    flags = ['-D' + d for d in info['MOC_DEFINITIONS']]
    flags += ['-I' + str(STAGE), '-I' + str(auto)]
    flags += ['-I' + p for p in info['MOC_INCLUDES'] if Path(p).is_dir() and 'plugins/filters/filtermanager' not in p.replace(chr(92), '/')]
    flags = [f.replace('kritafiltermanager_EXPORTS', 'kritatfm_EXPORTS') for f in flags]
    includes = []
    for p in files:
        text = p.read_text(encoding='utf-8', errors='replace')
        if p.suffix == '.h' and re.search(r'\bQ_OBJECT\b', text):
            name = 'moc_' + p.stem + '.cpp'
            subprocess.run([str(DEPS / 'bin/moc.exe'), *flags, str(STAGE / p.name), '-o', str(auto / name)], env=env, check=True)
            includes.append('#include "' + name + '"')
        if p.suffix == '.cpp':
            for name in re.findall(r'#include\s+"([^"\n]+\.moc)"', text):
                subprocess.run([str(DEPS / 'bin/moc.exe'), *flags, str(STAGE / p.name), '-o', str(auto / name)], env=env, check=True)
    (auto / 'mocs_compilation.cpp').write_text('\n'.join(includes) + '\n')
    entries = [e for e in json.loads((HOST / 'compile_commands.json').read_text()) if 'kritafiltermanager.dir' in e.get('output', '')]
    cmaketext = (PROJECT / 'src/CMakeLists.txt').read_text()
    source_match = re.search(r'set\(KRITA_FXMANAGER_SOURCES(.*?)\)', cmaketext, re.S)
    if source_match is None:
        raise SystemExit('Missing KRITA_FXMANAGER_SOURCES')
    required = set(re.findall(r'\b[\w.-]+\.cpp\b', source_match.group(1)))
    actual = {Path(e['file']).name.replace('filtermanager', 'fxmanager') for e in entries} - {'mocs_compilation.cpp'}
    stale = actual - required
    if stale:
        raise SystemExit(f'Reference source has stale entries: {stale}')
    extra_sources = sorted(required - actual)
    template_entry = next(e for e in entries if Path(e['file']).name != 'mocs_compilation.cpp')
    for extra_name in extra_sources:
        synth = dict(template_entry)
        synth['file'] = str(STAGE / extra_name)
        entries.append(synth)
    graph = ['rule compile', '  command = ' + str(COMPILER).replace('\\', '/') + ' @$rsp', '  description = COMPILE $out', 'rule link', '  command = ' + str(COMPILER).replace('\\', '/') + ' @$rsp', '  description = LINK $out']
    objects, database = [], []
    for e in entries:
        args = split(e['command'])[1:]
        # CommandLineToArgvW preserves quoted pkgconfig include/library paths;
        # never use whitespace splitting on generated flags.
        source = Path(e['file'])
        if source.name == 'mocs_compilation.cpp':
            source = auto / source.name
        else:
            source = STAGE / source.name.replace('filtermanager', 'fxmanager')
            if not source.is_file():
                raise SystemExit('Missing staged source: ' + str(source))
        obj = OUT / 'obj' / (source.name + '.obj')
        obj.parent.mkdir(exist_ok=True)
        args[args.index('-o') + 1] = str(obj)
        args[args.index('-c') + 1] = str(source)
        args = [a.replace('kritafiltermanager_EXPORTS', 'kritatfm_EXPORTS') for a in args]
        args = [a.replace('Krita-FilterManager', 'Krita-TFM/native/fx') for a in args]
        args = [a for a in args if 'plugins/filters/filtermanager' not in a.replace(chr(92), '/')]
        args[0:0] = ['-I' + str(STAGE), '-I' + str(auto), '-I' + str(PROJECT / 'src'),
                      '-I' + str(PROJECT / 'third_party/vulkan-headers/include')]
        rsp = obj.with_suffix('.rsp')
        args = [a.replace('\\', '/') if not a.startswith('-D') else a for a in args]
        rsp.write_text(subprocess.list2cmdline(args), encoding='utf-8')
        graph += ['build ' + escape(obj) + ': compile ' + escape(source) + ' | ' + ' '.join(escape(STAGE / p.name) for p in files), '  rsp = ' + subprocess.list2cmdline([str(rsp)])]
        objects.append(obj)
        database.append({'directory': str(HOST), 'file': str(source), 'arguments': [str(COMPILER), *args], 'output': str(obj)})
    text = (HOST / 'build.ninja').read_text()
    link_match = re.search(r'^build bin/kritafiltermanager\.dll:.*?(?=\n\n)', text, re.M | re.S)
    if link_match is None:
        raise SystemExit('Missing FXM link rule in reference build.ninja')
    block = link_match.group()
    values = dict(re.findall(r'^  (\w+) = (.*)$', block, re.M))
    libs = split(values['LINK_LIBRARIES'])
    for lib in libs:
        if not lib.startswith('-') and not (HOST / lib).is_file():
            raise SystemExit('Missing existing library: ' + lib)
    dll = OUT / 'bin/kritatfm.dll'
    candidate = OUT / 'bin/kritatfm.candidate.dll'
    dll.parent.mkdir(exist_ok=True)
    args = split(values['LANGUAGE_COMPILE_FLAGS']) + split(values['LINK_FLAGS'])
    args += ['-shared', '-o', str(candidate), '-Wl,--major-image-version,0,--minor-image-version,0']
    args += [str(p) for p in objects] + libs
    rsp = OUT / 'link.rsp'
    args = [a.replace('\\', '/') if not a.startswith('-D') else a for a in args]
    rsp.write_text(subprocess.list2cmdline(args), encoding='utf-8')
    graph += ['build ' + escape(candidate) + ': link ' + ' '.join(escape(p) for p in objects), '  rsp = ' + subprocess.list2cmdline([str(rsp)]), 'default ' + escape(candidate)]
    (OUT / 'build.ninja').write_text('\n'.join(graph) + '\n')
    (OUT / 'compile_commands.json').write_text(json.dumps(database, indent=2))
    command = [ninja, '-f', str(OUT / 'build.ninja'), '-j8']
    print('RUN', subprocess.list2cmdline(command), 'CWD', HOST, flush=True)
    subprocess.run(command, cwd=HOST, env=env, check=True)
    if before != {p.name: digest(p) for p in files}:
        raise SystemExit('Sources changed during build; rerun before validating candidate')
    # A failed compile/link never replaces the previous working artifact.
    # Preserve immutable rollback copies before atomically publishing the DLL.
    if dll.is_file():
        rollback = OUT / 'rollback' / digest(dll)
        rollback.mkdir(parents=True, exist_ok=True)
        if not (rollback / dll.name).exists():
            shutil.copy2(dll, rollback / dll.name)
        if (OUT / 'manifest.json').is_file() and not (rollback / 'manifest.json').exists():
            shutil.copy2(OUT / 'manifest.json', rollback / 'manifest.json')
    os.replace(candidate, dll)
    manifest = {'dll': str(dll), 'sha256': digest(dll), 'sources': before, 'compiler': str(COMPILER), 'cmake': cmake, 'ninja': ninja}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print('BUILD_OK', dll, 'SHA256', manifest['sha256'], flush=True)


if __name__ == '__main__':
    main()
