"""Run a named verification suite with explicit prerequisites and machine-readable results."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('unit', 'host', 'native', 'experimental')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=(*SUITES, 'all'), default='unit')
    parser.add_argument('--krita-root', type=Path)
    parser.add_argument('--model', type=Path, help='Opt-in BiRefNet model for native inference tests')
    parser.add_argument('--locale', choices=('en_US', 'zh_CN', 'both'), default='both')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/test-results')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 13):
        parser.error('Use Python 3.13 with requirements-test.txt (primary Qt5 test environment)')
    suites = SUITES if args.suite == 'all' else (args.suite,)
    locales = ('en_US', 'zh_CN') if args.locale == 'both' else (args.locale,)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for suite in suites:
        for locale in locales if suite in ('unit', 'host') else ('en_US',):
            label = f'{suite}-{locale}'
            started = time.monotonic()
            with tempfile.TemporaryDirectory(prefix='tfm-tests-') as temporary:
                env = dict(os.environ, QT_QPA_PLATFORM='offscreen', TFM_TEST_LOCALE=locale,
                           KLOCALAPPDATA=temporary, TMPDIR=temporary, PYTHONUTF8='1',
                           TFM_TEST_ARTIFACTS=str(out))
                if args.krita_root:
                    env['KRITA_ROOT'] = str(args.krita_root.resolve())
                if args.model:
                    env['TFM_TEST_MODEL'] = str(args.model.resolve())
                missing = suite == 'host' and not env.get('KRITA_ROOT')
                if missing:
                    results.append({'suite': label, 'status': 'unavailable', 'reason': 'KRITA_ROOT not configured'})
                    print(label, 'UNAVAILABLE: KRITA_ROOT not configured', flush=True)
                    continue
                selection = {'unit': 'not host and not experimental', 'host': 'host',
                             'native': 'not experimental', 'experimental': 'experimental'}[suite]
                paths = ['native/fx/tests'] if suite == 'native' else ['tests']
                command = [sys.executable, '-m', 'pytest', *paths, '-m', selection,
                           '-q', '--tb=short', f'--junitxml={out / (label + ".xml")}']
                if suite == 'experimental':
                    command.append('--run-experimental')
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
                (out / (label + '.log')).write_text(result.stdout, encoding='utf-8')
                print(result.stdout if args.verbose else '\n'.join(result.stdout.splitlines()[-16:]), flush=True)
                report = out / (label + '.xml')
                cases = ET.parse(report).findall('.//testcase') if report.exists() else []
                skipped = sum(case.find('skipped') is not None for case in cases)
                status = 'failed' if result.returncode else ('passed_with_skips' if skipped else 'passed')
                if not result.returncode and (not cases or skipped == len(cases)):
                    status = 'unavailable'
                results.append({'suite': label, 'status': status, 'tests': len(cases), 'skipped': skipped,
                                'exit_code': result.returncode, 'seconds': time.monotonic() - started,
                                'report': label + '.xml'})
    (out / (args.suite + '-summary.json')).write_text(json.dumps(results, indent=2), encoding='utf-8')
    # Unavailable suites are not success; individual pytest skips remain explicit in XML.
    return 1 if any(r['status'] in ('failed', 'unavailable') for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
