#!/usr/bin/env python3
"""Probe the 15 stubborn rows: what the survivor says about itself, and which

still-unused originals agree on DateTimeOriginal + dimensions."""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/probe_last15.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
import subprocess
from collections import defaultdict

W = '/home/lario/photos-reorg-work'
BK = '/mnt/xfs/photos-originals-backup'
NEW = '/home/lario/Pictures/Photos.new'
ET = '/home/lario/.local/bin/exiftool'
DATE_CHAIN = ['exif:datetimeoriginal', 'exififd:datetimeoriginal', 'ifd0:datetimeoriginal']


def norm(d):
    return {k.lower(): v for k, v in d.items()}


def dt_of(m):
    for k in DATE_CHAIN:
        if m.get(k):
            return str(m[k])[:19]
    return None


def dims_of(m):
    mm = re.match(r'(\d+)x(\d+)', str(m.get('composite:imagesize') or ''))
    return (int(mm.group(1)), int(mm.group(2))) if mm else None


def main():
    audit = json.load(open(os.path.join(W, 'moves-final-audit.json')))
    open_new = [x['new'] for x in audit['ambiguous'] if 'perceptual' in x['why']]
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    used = {r['orig'] for r in rows}
    recs = json.load(open(os.path.join(W, 'meta_backup_dates.json')))
    by_dt = defaultdict(list)
    bak = {}
    for r in recs:
        src = r.get('SourceFile')
        if not src:
            continue
        rel = os.path.relpath(src, BK)
        m = norm(r)
        bak[rel] = dict(dt=dt_of(m), dims=dims_of(m))
        if rel not in used:
            by_dt[dt_of(m)].append(rel)
    print('unused originals indexed by DateTimeOriginal:', len(set(map(str, by_dt))))

    for rel in open_new:
        out = subprocess.run([ET, '-json', '-G1', '-api', 'Binary=0',
                              os.path.join(NEW, rel)], capture_output=True, text=True).stdout
        try:
            m = norm(json.loads(out)[0])
        except Exception:
            print(rel, 'unreadable')
            continue
        dt, nd = dt_of(m), dims_of(m)
        cand = [o for o in by_dt.get(dt, []) if bak[o]['dims'] == nd]
        print(f'\n{rel}\n  dt={dt} dims={nd} unused-same-dt={len(by_dt.get(dt, []))} '
              f'+same-dims={len(cand)}')
        for o in cand[:6]:
            print('   ', o)


if __name__ == "__main__":
    main()
