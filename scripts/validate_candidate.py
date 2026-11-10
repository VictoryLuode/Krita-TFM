"""Bind the production acceptance suites to one complete candidate batch."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_artifacts import validated_current, write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--krita-root',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,13):parser.error('Run with the declared Python 3.13 test environment')
    _batch,manifest=validated_current(ROOT)
    output=ROOT/'build/test-results/candidate-validation.json'
    report={'schema_version':1,'batch_id':manifest['batch_id'],'status':'running','suites':[],
            'live_host':{'status':'unverified','reason':'Windows Known Folder profile isolation unavailable; no daily-host test was performed'},
            'external_search_provider':{'status':'unverified','reason':'Network regression used a local controlled server'}}
    write_json(output,report)
    started=time.monotonic()
    try:
        for command in ([sys.executable,'scripts/generate_filter_metadata.py','--check'],
                        [sys.executable,'native/fx/compile_shaders.py','--all','--check']):
            subprocess.run(command,cwd=ROOT,check=True)
        for suite in ('unit','host','native'):
            subprocess.run([sys.executable,'scripts/test.py','--suite',suite,'--locale','both',
                            '--krita-root',str(args.krita_root),'--model',str(args.model)],cwd=ROOT,check=True)
            summary=json.loads((ROOT/f'build/test-results/{suite}-summary.json').read_text(encoding='utf-8'))
            report['suites'].extend(summary)
            if any(row['status']!='passed' for row in summary):
                raise RuntimeError('Candidate validation requires explicit full production coverage: '+suite)
        if validated_current(ROOT)[1]['batch_id']!=manifest['batch_id']:
            raise RuntimeError('Candidate changed during validation')
        report['status']='passed_with_live_host_gap'
    except Exception as error:
        report['status']='failed';report['error']=str(error)
        raise
    finally:
        report['seconds']=time.monotonic()-started
        write_json(output,report)
    print('VALIDATED_CANDIDATE',manifest['batch_id'],report['status'])


if __name__=='__main__':main()
