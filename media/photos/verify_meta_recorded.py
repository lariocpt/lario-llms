#!/usr/bin/env python3
"""Re-runnable metadata check that needs no originals.


verify_meta.py compared the new files against the backup originals and, at
09:38, reported all 6 458 changed files identical on dimensions, orientation,
DateTimeOriginal, offset, GPS, Make and Model (verify-meta-final.log). It cannot
run any more: the backup is gone, and re-running it truncated its cached
original-tag dump (vmeta_orig.json) to zero bytes.

This version reads the originals' metadata from meta_backup.json instead - the
scan rescan.py took of the backup at 02:12, with the same exiftool tags and the
same formatting (no -n, so GPS stays as the same DMS strings). So the comparison
is still original-vs-live, and it covers every survivor, not only the ones whose
bytes changed.

Tags covered: FileType, pixel dimensions, ImageSize, DateTimeOriginal,
OffsetTimeOriginal, Orientation, GPS latitude/longitude. Make/Model were not in
that scan - they rest on the 09:38 result only.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/verify_meta_recorded.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import subprocess
import sys

W = '/home/lario/photos-reorg-work'
from paths import LIB
ET = '/home/lario/.local/bin/exiftool'
TAGS = ['-G0', '-m', '-q', '-j', '-api', 'LargeFileSupport=1',
        '-file:FileType', '-File:ImageWidth', '-File:ImageHeight',
        '-Composite:ImageSize', '-ExifIFD:DateTimeOriginal',
        '-ExifIFD:OffsetTimeOriginal', '-ExifIFD:Orientation',
        '-GPSLatitude', '-GPSLongitude', '-Composite:GPSLatitude',
        '-Composite:GPSLongitude']
BATCH = 600


def scan(paths):
    out = {}
    for i in range(0, len(paths), BATCH):
        chunk = paths[i:i + BATCH]
        r = subprocess.run([ET] + TAGS + chunk, capture_output=True, text=True)
        try:
            recs = json.loads(r.stdout or '[]')
        except Exception:
            recs = []
            for p in chunk:
                rr = subprocess.run([ET] + TAGS + [p], capture_output=True, text=True)
                try:
                    recs += json.loads(rr.stdout or '[]')
                except Exception:
                    pass
        for rec in recs:
            src = rec.get('SourceFile')
            if src:
                out[src] = {k: v for k, v in rec.items() if not k.startswith('[')}
    return out


def main():
    rec = json.load(open(os.path.join(W, 'meta_backup.json')))
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8')))
    missing = [r for r in rows if r['orig'] not in rec]
    print(f'survivors {len(rows)}   no recorded original metadata: {len(missing)}', flush=True)
    live = scan([os.path.join(LIB, r['new']) for r in rows])
    print(f'live files read: {len(live)}', flush=True)

    tags = ['File:FileType', 'File:ImageWidth', 'File:ImageHeight', 'Composite:ImageSize',
            'EXIF:DateTimeOriginal', 'EXIF:OffsetTimeOriginal', 'EXIF:Orientation',
            'EXIF:GPSLatitude', 'EXIF:GPSLongitude', 'Composite:GPSLatitude',
            'Composite:GPSLongitude']
    diff_count, problems, same = {}, [], 0
    for r in rows:
        # meta_backup.json is keyed by path relative to the backup root; its
        # SourceFile value is the absolute path under it.
        a, b = rec.get(r['orig'], {}), live.get(os.path.join(LIB, r['new']), {})
        if not b:
            problems.append({'new': r['new'], 'why': 'exiftool could not read the live file'})
            continue
        d = {}
        for t in tags:
            va, vb = a.get(t), b.get(t)
            if va is None or vb is None:
                if (va is None) != (vb is None) and t != 'EXIF:OffsetTimeOriginal':
                    d[t] = [va, vb]      # present on one side only
            elif str(va) != str(vb):
                d[t] = [va, vb]
        if d:
            diff_count[tuple(sorted(d))] = diff_count.get(tuple(sorted(d)), 0) + 1
            problems.append({'new': r['new'], 'orig': r['orig'], 'diff': d})
        else:
            same += 1
    print(f'metadata matches the recorded original: {same}   differing: '
          f'{sum(1 for p in problems if "diff" in p)}')
    for k, v in sorted(diff_count.items(), key=lambda x: -x[1])[:12]:
        print(f'  {v:>5}  {", ".join(k)}')
    for p in [x for x in problems if 'diff' in x][:10]:
        print('   ', json.dumps(p, ensure_ascii=False)[:220])
    json.dump({'checked': len(rows), 'matches': same, 'problems': problems},
              open(os.path.join(W, 'verify-meta-recorded.json'), 'w'), indent=1)
    print('total problems:', len(problems), file=sys.stderr)


if __name__ == "__main__":
    main()
