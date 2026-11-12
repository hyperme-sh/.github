#!/usr/bin/env python3
"""Compare current Spanopticon and bundled preparation in the scheduled batch."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from stable_policy.preparation_contract import exercise


def qualify(source, output):
    if os.environ.get('GITHUB_EVENT_NAME') != 'schedule' or os.environ.get('GITHUB_REPOSITORY') != 'hyperme-sh/.github' or os.environ.get('NIGHTLY_SUITE') != 'release-preparation-parity':
        raise ValueError('Central scheduled batch required')
    source, output = Path(source).resolve(), Path(output).resolve()
    vectors = json.loads((source / 'release/preparation-vectors.json').read_text())
    bundled = json.loads((Path(__file__).parent / 'stable_policy/preparation-vectors.json').read_text())
    suite = ET.Element('testsuite', name='release-preparation-parity')
    failures = 0
    for vector in vectors:
        case = ET.SubElement(suite, 'testcase', name=vector['case'], classname='preparation.parity')
        try:
            if vector not in bundled:
                raise ValueError('Current-source vector is absent from publisher')
            try:
                exercise(vector['case'])
                actual = True
            except ValueError:
                actual = False
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            program = '''import sys
sys.path.insert(0, sys.argv[1])
from release.preparation_contract import exercise
try:
    exercise(sys.argv[2])
    print('accepted')
except ValueError:
    print('refused')
'''
            response = subprocess.check_output([sys.executable, '-I', '-c', program, str(source), vector['case']],
                                               cwd=source, env=env, timeout=60).decode().strip()
            if response not in {'accepted', 'refused'} or actual is not vector['accepted'] or actual != (response == 'accepted'):
                raise ValueError('Divergent preparation outcome')
        except Exception:
            failures += 1
            ET.SubElement(case, 'failure', message='Preparation prerequisite or parity failure')
    if not vectors:
        failures += 1
        ET.SubElement(ET.SubElement(suite, 'testcase', name='nonempty-vectors'), 'failure', message='No preparation vectors')
    suite.set('tests', str(len(suite)))
    suite.set('failures', str(failures))
    output.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(output / 'preparation-parity.xml', encoding='utf-8', xml_declaration=True)
    if failures:
        raise ValueError('Preparation parity failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spanopticon-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    qualify(args.spanopticon_root, args.output)
