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
import sys
import tempfile
import runpy
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent          # Krita-TFM/native/fx
REPO = PROJECT.parents[1]                          # Krita-TFM
HOST = REPO / 'Krita-Master-5.3.4.1' / 'build-fxm-5.3'
STAGE = REPO / 'build' / 'native-5.3' / 'stage'
OUT = REPO / 'build' / 'native-5.3'
DEPS = REPO / 'deps'
sys.path.insert(0, str(REPO))
from build_artifacts import source_inputs, publish_batch
from compile_shaders import generate_all, find_compiler
# Reference graphs may retain absolute prefixes from older layouts
# ("Krita Addon", under KritaAddon/, or the previous KritaAddon/Krita-TFM path).
# Rewrite only those prefixes in generated compiler/link args; never edit host files.


def normalize_dep_arg(value):
    text = str(value).replace('\\', '/')
    repo = str(REPO).replace('\\', '/')
    text = re.sub(r'[A-Za-z]:/Dev/Krita Addon(?:/Krita-TFM)?', repo, text)
    text = re.sub(r'[A-Za-z]:/Dev/KritaAddon/Krita-TFM', repo, text)
    text = re.sub(
        r'[A-Za-z]:/Dev/KritaAddon(?=/(?:deps|Krita-Master-5\.3\.4\.1)(?:/|$))',
        repo,
        text,
    )
    return text


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


def build_vulkan_worker(env, destination):
    """Link the Vulkan device into its own process, never into kritatfm.dll."""
    device_src = PROJECT / 'src' / 'fxmanager_vulkan_device.cpp'
    worker_src = PROJECT / 'src' / 'tfm_vulkan_worker.cpp'
    if not device_src.is_file() or not worker_src.is_file():
        raise SystemExit('Missing Vulkan worker sources')
    obj_dir = OUT / 'obj'
    obj_dir.mkdir(parents=True, exist_ok=True)
    includes = ['-I' + str(PROJECT / 'src'),
                '-I' + str(PROJECT / 'third_party' / 'vulkan-headers' / 'include')]
    objects = []
    for src in (device_src, worker_src):
        obj = obj_dir / (src.name + '.obj')
        subprocess.run([str(COMPILER), '-std=c++17', '-O2', '-DNDEBUG', '-c', str(src), '-o', str(obj), *includes],
                       env=env, check=True)
        objects.append(obj)
    exe = destination / 'tfm_vulkan_worker.exe'
    exe.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(COMPILER), '-O2', '-o', str(exe), *[str(obj) for obj in objects]], env=env, check=True)
    linked = {path.name for path in objects}
    if 'fxmanager_vulkan.cpp.obj' in linked:
        raise SystemExit('Refusing to link the in-process Vulkan client into the worker')
    ping = subprocess.run([str(exe), '--ping'], env=env, capture_output=True, text=True, timeout=10)
    print('VULKAN_WORKER_PING', ping.returncode, ping.stdout.strip(), ping.stderr.strip(), flush=True)
    if ping.returncode not in (0, 1):
        raise SystemExit('Vulkan worker failed to start')
    return exe


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
    runpy.run_path(str(REPO / 'scripts/generate_filter_metadata.py'))['generate']()
    shader_compiler = find_compiler()
    print('SHADERS', generate_all(shader_compiler), flush=True)
    input_hashes = source_inputs(REPO)
    # Build the actual vendored sources, never silently reuse reference-project archives.
    inference = OUT / 'inference'
    prefix_map = '-ffile-prefix-map=' + REPO.as_posix() + '=.'
    subprocess.run([cmake, '-S', str(PROJECT / 'inference'), '-B', str(inference), '-G', 'Ninja',
                    '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=' + str(COMPILER.with_name('clang.exe')),
                    '-DCMAKE_CXX_COMPILER=' + str(COMPILER), '-DCMAKE_C_FLAGS=' + prefix_map,
                    '-DCMAKE_CXX_FLAGS=' + prefix_map], env=env, check=True)
    subprocess.run([cmake, '--build', str(inference), '--parallel', '8'], env=env, check=True)
    local_archives = {p.name.removeprefix('lib'): p for p in (inference / 'lib').glob('*.a')}
    files = sorted(p for p in (PROJECT / 'src').iterdir() if p.is_file() and
                   (p.suffix in {'.cpp', '.h', '.json', '.qrc', '.ui'} or p.name == 'CMakeLists.txt'))
    before = {p.name: digest(p) for p in files}
    STAGE.mkdir(parents=True, exist_ok=True)
    for p in files:
        target = STAGE / p.name
        if not target.is_file() or digest(target) != before[p.name]:
            shutil.copy2(p, target)
        if p.name == 'fxmanager_plugin.cpp':
            text = target.read_text(encoding='utf-8')
            text = text.replace('FxManagerPluginFactory', 'FilterManagerFactory')
            target.write_text(text, encoding='utf-8')
    OUT.mkdir(parents=True, exist_ok=True)
    auto = OUT / 'autogen'
    auto.mkdir(exist_ok=True)
    info = json.loads((HOST / 'plugins/filters/filtermanager/CMakeFiles/kritafiltermanager_autogen.dir/AutogenInfo.json').read_text())
    flags = ['-D' + d for d in info['MOC_DEFINITIONS']]
    flags += ['-I' + str(STAGE), '-I' + str(auto)]
    flags += ['-I' + normalize_dep_arg(p) for p in info['MOC_INCLUDES']
              if Path(normalize_dep_arg(p)).is_dir() and 'plugins/filters/filtermanager' not in p.replace(chr(92), '/')]
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
                output = auto / name
                if p.name == 'fxmanager_plugin.cpp' and name == 'fxmanager_plugin.moc':
                    host_moc = HOST / 'plugins/filters/filtermanager/kritafiltermanager_autogen/include/filtermanager_plugin.moc'
                    if not host_moc.is_file():
                        raise SystemExit('Missing reference plugin moc: ' + str(host_moc))
                    moc_text = host_moc.read_text(encoding='utf-8', errors='replace')
                    moc_text = moc_text.replace('FilterManagerFactory', 'FilterManagerFactory')
                    moc_text = moc_text.replace('filtermanager_plugin.cpp', 'fxmanager_plugin.cpp')
                    output.write_text(moc_text, encoding='utf-8')
                else:
                    subprocess.run([str(DEPS / 'bin/moc.exe'), *flags, str(STAGE / p.name), '-o', str(output)], env=env, check=True)
            # Explicit .moc files are included by their originating .cpp.
            # They must not be added to mocs_compilation.cpp.
            continue
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
    if any('fxmanager_vulkan_device.cpp' in str(entry.get('file', '')) for entry in entries):
        raise SystemExit('Vulkan device code must not be compiled into kritatfm.dll')
    plugin_cpp = (PROJECT / 'src/fxmanager_plugin.cpp').read_text()
    moc_outputs = [auto / name for name in re.findall(r'#include\s+"([^"\n]+\.moc)"', plugin_cpp)]
    for e in entries:
        args = split(e['command'])[1:]
        args = [normalize_dep_arg(a) for a in args]
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
        args = [a for a in args if
                'plugins/filters/filtermanager' not in a.replace(chr(92), '/') or
                'third_party/visioncpp' in a.replace(chr(92), '/') or
                'third_party/ggml' in a.replace(chr(92), '/')]
        args[0:0] = [prefix_map, '-I' + str(STAGE), '-I' + str(auto), '-I' + str(PROJECT / 'src'),
                      '-I' + str(PROJECT / 'third_party/vulkan-headers/include'),
                      '-I' + str(PROJECT / 'third_party/visioncpp/include'),
                      '-I' + str(PROJECT / 'third_party/visioncpp/src'),
                      '-I' + str(PROJECT / 'third_party/visioncpp/depend/stb'),
                      '-I' + str(PROJECT / 'third_party/ggml/include'),
                      '-I' + str(PROJECT / 'third_party/ggml/src')]
        rsp = obj.with_suffix('.rsp')
        args = [a.replace('\\', '/') if not a.startswith('-D') else a for a in args]
        rsp.write_text(subprocess.list2cmdline(args), encoding='utf-8')
        deps = [STAGE / p.name for p in files]
        if source.name == 'fxmanager_plugin.cpp':
            deps += moc_outputs
        graph += ['build ' + escape(obj) + ': compile ' + escape(source) + ' | ' + ' '.join(escape(p) for p in deps), '  rsp = ' + subprocess.list2cmdline([str(rsp)])]
        objects.append(obj)
        database.append({'directory': str(HOST), 'file': str(source), 'arguments': [str(COMPILER), *args], 'output': str(obj)})
    text = (HOST / 'build.ninja').read_text()
    link_match = re.search(r'^build bin/kritafiltermanager\.dll:.*?(?=\n\n)', text, re.M | re.S)
    if link_match is None:
        raise SystemExit('Missing FXM link rule in reference build.ninja')
    block = link_match.group()
    values = dict(re.findall(r'^  (\w+) = (.*)$', block, re.M))
    libs = [normalize_dep_arg(lib) for lib in split(values['LINK_LIBRARIES'])]
    own_archives = {'visioncpp.a', 'ggml.a', 'ggml-cpu.a', 'ggml-base.a', 'filtermanager_stb.a'}
    for index, lib in enumerate(libs):
        name = Path(lib).name.removeprefix('lib')
        if name in own_archives:
            if name not in local_archives:
                raise SystemExit('Missing rebuilt inference archive: ' + name)
            libs[index] = str(local_archives[name])
    linked_inputs = {Path(lib).name: digest(Path(lib) if Path(lib).is_absolute() else HOST / lib)
                     for lib in libs if not lib.startswith('-')}
    for lib in libs:
        if not lib.startswith('-') and not (HOST / lib).is_file() and not Path(lib).is_file():
            raise SystemExit('Missing existing library: ' + lib)
    pending = Path(tempfile.mkdtemp(prefix='pending-', dir=OUT))
    candidate = pending / 'kritatfm.dll'
    args = [normalize_dep_arg(a) for a in split(values['LANGUAGE_COMPILE_FLAGS']) + split(values['LINK_FLAGS'])]
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
    worker = build_vulkan_worker(env, pending)
    subprocess.run([str(COMPILER.with_name('clang.exe')), '-shared', '-O2', '-ffast-math',
                    '-o', str(pending / 'tfm_color_range.dll'), str(REPO / 'native/color_range.c')],
                   env=env, check=True)
    # Distribution binaries do not carry local source/debug paths.
    strip = COMPILER.with_name('llvm-strip.exe')
    for name in ('kritatfm.dll', 'tfm_vulkan_worker.exe', 'tfm_color_range.dll'):
        subprocess.run([str(strip), '--strip-debug', str(pending / name)], env=env, check=True)
    if source_inputs(REPO) != input_hashes:
        raise SystemExit('Inputs changed during build; previous complete batch retained')
    def tool_version(executable, option='--version'):
        output = subprocess.check_output([str(executable), option], env=env, text=True, timeout=10).strip()
        return '\n'.join(line for line in output.splitlines()
                         if not line.startswith(('InstalledDir:', 'Configuration file:')))
    manifest = {'sources': before, 'inputs': input_hashes, 'linked_libraries': linked_inputs,
                'toolchain': {'compiler': tool_version(COMPILER), 'cmake': tool_version(cmake),
                              'ninja': tool_version(ninja), 'glslang': tool_version(shader_compiler),
                              'qt': '5', 'krita': '5.3.4.1'},
                'generated': {name: value for name, value in input_hashes.items()
                              if name.endswith('_spv.h') or name.endswith('/filter_metadata.h')
                              or name == 'pykrita/tfm/filters/catalog.py'}}
    batch = publish_batch(OUT, pending, manifest)
    print('BUILD_OK', batch.name, flush=True)
    for binary in ('kritatfm.dll', 'tfm_vulkan_worker.exe', 'tfm_color_range.dll'):
        print('BINARY', binary, digest(batch / binary), flush=True)


if __name__ == '__main__':
    main()
