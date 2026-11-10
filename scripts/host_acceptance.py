"""Run the live-host probe in a private copied Krita install, never daily resources."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import ctypes
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_artifacts import validated_current, digest
from install_candidate import stage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--locale',choices=('en_US','zh_CN'),default='en_US')
    args=parser.parse_args()
    out=args.out.resolve()
    if not out.is_relative_to((ROOT/'build').resolve()) or out.exists():
        parser.error('Use a new evidence directory under this worktree build/')
    # Krita uses one per-user IPC key. Refuse to route automation into an existing host.
    processes=subprocess.check_output(['tasklist','/FI','IMAGENAME eq krita.exe','/FO','CSV','/NH'])
    if b'"krita.exe"' in processes.lower():
        parser.error('An existing Krita is running; live isolated probe not started')
    batch,manifest=validated_current(ROOT)
    out.mkdir(parents=True)
    # On this Windows/Qt5 distribution, QStandardPaths uses Known Folders and
    # ignores APPDATA/LOCALAPPDATA environment overrides. Check before starting
    # a GUI process; never mistake a private EXE for a private settings profile.
    if os.name == 'nt':
        folder = ctypes.create_unicode_buffer(32768)
        shell = ctypes.windll.shell32
        shell.SHGetFolderPathW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE,
                                         wintypes.DWORD, wintypes.LPWSTR]
        if shell.SHGetFolderPathW(None, 0x001c, None, 0, folder) == 0:
            known = Path(folder.value).resolve()
            if not known.is_relative_to(out):
                reason = ('Windows Known Folder still resolves outside the private profile; '
                          'live GUI acceptance requires an independently isolated OS user/environment')
                (out/'result.json').write_text(json.dumps({'status':'unavailable', 'reason':reason,
                    'batch_id':manifest['batch_id'], 'host_started':False},indent=2),encoding='utf-8')
                print(reason)
                return 2
    runtime=out/'runtime';resource=out/'resource';profile=out/'profile'
    def ignore(_directory,names):
        excluded={'kritatfm.dll','kritafxmanager.dll','kritafiltermanager.dll','tfm_vulkan_worker.exe'}
        return [name for name in names if name.lower() in excluded or name.endswith('.pdb')]
    shutil.copytree(args.runtime,runtime,ignore=ignore)
    resource.mkdir();profile.mkdir()
    stage(resource,native_directory=runtime/'lib/kritaplugins')
    probe=resource/'pykrita/quality_probe';probe.mkdir()
    shutil.copy2(ROOT/'tests/quality_host_probe.py',probe/'__init__.py')
    (resource/'pykrita/quality_probe.desktop').write_text(
        '[Desktop Entry]\nType=Service\nServiceTypes=Krita/PythonPlugin\nX-KDE-Library=quality_probe\n'
        'X-Python-2-Compatible=false\nName=TFM isolated quality probe\n',encoding='utf-8')
    config='ResourceDirectory='+resource.as_posix()+'\nLastVersion=5.3.4.1\n[python]\nenable_tfm=true\nenable_quality_probe=true\n'
    (profile/'kritarc').write_text(config,encoding='utf-8')
    (profile/'klanguageoverridesrc').write_text('[Language]\nkrita='+args.locale+'\n',encoding='utf-8')
    env=dict(os.environ,KLOCALAPPDATA=str(profile),LOCALAPPDATA=str(profile),APPDATA=str(profile),
             TFM_HOST_EVIDENCE=str(out),TFM_HOST_RESOURCE=str(resource),TFM_LOG_DIR=str(out/'logs'),
             KRITA_PLUGIN_PATH=str(runtime/'lib/kritaplugins'),QT_PLUGIN_PATH=str(runtime/'bin'),
             TFM_TEST_LOCALE=args.locale,LANGUAGE=args.locale,LANG=args.locale,PYTHONUTF8='1')
    env.pop('QT_QPA_PLATFORM',None)
    env['PATH']=str(runtime/'bin')+os.pathsep+env.get('PATH','')
    (out/'provenance.json').write_text(json.dumps({'batch_id':manifest['batch_id'],
        'probe_sha256':digest(ROOT/'tests/quality_host_probe.py'),'locale':args.locale,
        'daily_install_modified':False},indent=2),encoding='utf-8')
    with (out/'host.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([str(runtime/'bin/krita.exe'),'--nosplash'],env=env,stdout=log,stderr=subprocess.STDOUT)
        (out/'process.json').write_text(json.dumps({'pid':process.pid}),encoding='utf-8')
        try:
            code=process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            # Only the process created above is terminated; no process-name kill.
            process.terminate();process.wait(timeout=10)
            raise SystemExit('Isolated host timed out; inspect '+str(out/'host.log'))
    result=json.loads((out/'result.json').read_text(encoding='utf-8')) if (out/'result.json').exists() else {}
    print(json.dumps({'exit_code':code,'status':result.get('status','no report'),
                      'checks':len(result.get('checks',[])),'evidence':str(out)},indent=2))
    if code or result.get('status')!='passed':
        print(result.get('error','Host exited before probe completion'))
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
