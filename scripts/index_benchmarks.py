#!/usr/bin/env python3
"""Refresh the dated benchmark report's complete raw-artifact index."""
import argparse
from datetime import date
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '<!-- BEGIN GENERATED RESULT INDEX -->'
END = '<!-- END GENERATED RESULT INDEX -->'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    path = ROOT/'docs'/f'benchmarks-{args.date.isoformat()}.md'
    source = path.read_text()
    entries = ['| Artifact | Scope | Stored result |', '| --- | --- | --- |']
    files = sorted(set((ROOT/'research/benchmarks').glob('*.json')) |
                   set((ROOT/'intel/research').glob('*.json')))
    for file in files:
        data = json.loads(file.read_text())
        if not isinstance(data, dict):continue
        rows = data.get('rows', [])
        scope = data.get('suite') or data.get('model') or ('telemetry' if 'samples' in data else 'runtime / device checks')
        if isinstance(rows,list) and rows:
            status = f"{sum(bool(row.get('passed')) for row in rows)}/{len(rows)} stored rows passed"
        elif 'pass' in data or 'passed' in data:
            status = 'PASS' if data.get('pass',data.get('passed')) else 'FAIL'
        elif 'samples' in data:
            samples = data['samples']
            status = f"{len(samples) if isinstance(samples,list) else samples} samples"
        elif data.get('exit') == 0:
            status = 'exit 0; see assertions'
        else:status = 'see artifact'
        label = str(scope).replace('|','\\|').replace('\n',' ')
        entries.append(f'| [{file.stem}](../{file.relative_to(ROOT).as_posix()}) | {label} | {status} |')
    path.write_text(source.split(BEGIN)[0]+BEGIN+'\n'+'\n'.join(entries)+'\n'+END+source.split(END)[1])
    print('indexed',len(files),'artifacts')


if __name__ == '__main__':main()
