"""Link a native regression against the current, source-verified production build."""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile

from run_native_util import split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build','deps','runtime','out','test'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--model',type=Path)
    args = parser.parse_args()
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    root = Path(__file__).resolve().parents[1]
    build, out, runtime = args.build.resolve(), args.out.resolve(), args.runtime.resolve()
    out.mkdir(parents=True,exist_ok=True)
    manifest = json.loads((build/'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['sources'].items():
        source = root/'src'/name
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
            parser.error('stale production build: '+name+'; rebuild before testing')
    entries = json.loads((build/'compile_commands.json').read_text(encoding='utf-8'))
    entry = next(e for e in entries if e['file'].endswith('tfm_vibrance.cpp'))
    command = entry['arguments']
    compiler, flags = command[0], command[1:command.index('-o')]
    env = dict(os.environ,QT_PLUGIN_PATH=str(runtime/'bin'),KRITA_PLUGIN_PATH=str(runtime/'lib/kritaplugins'),
               QT_QPA_PLATFORM='offscreen',TFM_KRITA_RUNTIME=str(runtime),FXMANAGER_KRITA_RUNTIME=str(runtime),TFM_THREADS='2',TFM_VULKAN_DISABLE='1',TFM_TEST_NATIVE_DLL=str(build/'bin/kritatfm.dll'))
    env['PATH'] = os.pathsep.join([str(runtime/'bin'),str(Path(entry['directory'])/'bin'),
                                  str(args.deps.resolve()/'bin'),str(Path(compiler).parent),env['PATH']])

    def run(command,label):
        with (out/(label+'.log')).open('w',encoding='utf-8') as log:
            result = subprocess.run([str(x) for x in command],cwd=entry['directory'],env=env,
                                    stdout=log,stderr=subprocess.STDOUT,timeout=120)
        if result.returncode or label=='result':
            print((out/(label+'.log')).read_text(encoding='utf-8',errors='replace'),flush=True)
        if result.returncode:
            raise SystemExit(f'{label} failed: 0x{result.returncode & 0xffffffff:08x}')

    test = args.test.resolve()
    obj,exe = out/'test.obj',out/'test.exe'
    run([compiler,'-I'+str(root/'src'),*flags,'-c',test,'-o',obj],'compile')
    link = split('compiler '+(build/'link.rsp').read_text(encoding='utf-8'))[1:]
    inputs = [a for a in link if a.endswith(('.obj','.a','.lib')) or a.startswith('-l')]
    run([compiler,obj,*inputs,'-o',exe],'link')
    with tempfile.TemporaryDirectory(prefix='tfm-native-profile-') as profile:
        resource=Path(profile)/'resource'; resource.mkdir()
        if args.model:
            destination=resource/'TFM/background-removal/models'/args.model.name
            destination.parent.mkdir(parents=True)
            shutil.copy2(args.model,destination)
        (Path(profile)/'kritarc').write_text('ResourceDirectory='+resource.as_posix()+'\n',encoding='utf-8')
        env.update(KLOCALAPPDATA=profile,LOCALAPPDATA=profile,APPDATA=profile)
        run([exe,out],'result')
    (out/'provenance.json').write_text(json.dumps({
        'production_sources':manifest['sources'],'test_sha256':hashlib.sha256(test.read_bytes()).hexdigest(),
        'status':'passed'},indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
