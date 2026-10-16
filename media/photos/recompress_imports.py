#!/usr/bin/env python3
"""Recompress the JPEGs imported from the hhd source trees, same rule as the

original pass: q85 baseline, replace only when that is >=10 % smaller, EXIF/GPS
re-injected from the pre-encode file, pixels never re-oriented (the orientation
tag is kept as-is so the library stays in one convention).

Every file is checked before and after: same real type, same pixel dimensions,
same orientation, same capture time, GPS present or absent as it was, and a PSNR
against its own original. Anything that fails any check keeps its original
bytes. PNG/TIFF are never re-encoded (their lossless content does not survive a
JPEG round trip).

  DRY=1  only report what would happen
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/recompress_imports.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import LIB
EXIF = os.path.expanduser('~/.local/bin/exiftool')
Q = 85
MIN_SAVE = 0.90        # replace only if at most 90 % of the original size
MIN_PSNR = 35.0        # dB against the file's own pixels, floor for accepting
WORKERS = 6
TAGS = ['-ImageSize', '-Orientation', '-DateTimeOriginal', '-CreateDate',
        '-GPSLatitude', '-GPSLongitude', '-Make', '-Model']


def read_tags(paths):
    out, recs = [], {}
    for i in range(0, len(paths), 500):
        r = subprocess.run([EXIF, '-q', '-j', '-n', '-G1', '-FileType', *TAGS]
                           + paths[i:i + 500], capture_output=True, text=True)
        for rec in json.loads(r.stdout or '[]'):
            recs[rec['SourceFile']] = rec
    return recs


def sig(rec):
    """The metadata signature that must be identical before and after."""
    return {k.split(':')[-1]: rec.get(k) for k in
            ('Composite:ImageSize', 'IFD0:Orientation', 'ExifIFD:DateTimeOriginal',
             'IFD0:DateTimeOriginal', 'QuickTime:CreateDate', 'IFD0:Make',
             'ExifIFD:GPSLatitude', 'GPS:GPSLatitude', 'Composite:GPSLatitude')}


def psnr(a, b):
    r = subprocess.run(['magick', 'compare', '-metric', 'PSNR', a, b, 'null:'],
                       capture_output=True, text=True)
    try:
        return float(r.stderr.split('(1e+00')[-1].split()[0])
    except (ValueError, IndexError):
        try:
            return float(r.stderr.split()[0])
        except (ValueError, IndexError):
            return None


def work(job):
    path, before = job
    tmp = path + '.q85.tmp'
    r = {'new': os.path.relpath(path, LIB), 'bytes_before': os.path.getsize(path)}
    try:
        p = subprocess.run(['magick', path, '-quality', str(Q), tmp],
                           capture_output=True, text=True)
        if not (p.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1024):
            r.update(status='encode-failed', detail=(p.stderr or '')[:120])
            return r
        subprocess.run([EXIF, '-overwrite_original', '-TagsFromFile', path,
                        '-all:all', tmp], capture_output=True, text=True)
        nb, na = os.path.getsize(path), os.path.getsize(tmp)
        if na > MIN_SAVE * nb:
            r.update(status='kept', bytes_after=na,
                     detail=f'q85 saves only {(1 - na / nb) * 100:.1f} %')
            return r
        after = read_tags([tmp])[tmp]
        b, a = sig(before), sig(after)
        bad = {k: (b.get(k), a.get(k)) for k in set(b) | set(a) if b.get(k) != a.get(k)}
        if bad:
            r.update(status='metadata-changed', detail=str(bad)[:200])
            return r
        dB = psnr(path, tmp)
        if dB is None or dB < MIN_PSNR:
            r.update(status='low-psnr', psnr=dB,
                     detail=f'{dB} dB vs own original, floor {MIN_PSNR}')
            return r
        r['psnr'] = dB
        with open(path, 'rb') as fh:
            digest_before = __import__('hashlib').blake2b(fh.read(), digest_size=32).hexdigest()
        os.replace(tmp, path)
        now = read_tags([path])[path]
        if sig(now) != sig(after):
            r.update(status='verify-failed-after-replace', detail='metadata drift')
            return r
        r.update(status='recompressed', bytes_after=os.path.getsize(path),
                 sha_before=digest_before)
        return r
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main():
    dry = os.environ.get('DRY') == '1'
    man = os.environ.get('MANIFEST', 'manifest-imports.csv')
    trees = [t for t in os.environ.get('TREES', '').split(',') if t]
    rows = list(csv.DictReader(open(f'{W}/{man}', encoding='utf-8')))
    if trees:
        rows_all = rows
        rows = [r for r in rows_all if r['src_tree'] in trees]
        print(f'filter src_tree in {trees}: {len(rows)} of {len(rows_all)} rows')
    # a file that already went through the q85 pass must not be re-encoded again
    todo_rows = [r for r in rows if 'recompressed' not in r['how']]
    print(f'skipping {len(rows) - len(todo_rows)} rows already recompressed')
    photos = [r for r in todo_rows if r['new'].lower().endswith('.jpg')
              or r['new'].lower().endswith('.jpeg')]
    paths = [os.path.join(LIB, r['new']) for r in photos]
    print(f'imported photos: {len(rows)}   JPEG candidates: {len(paths)}')
    pre = read_tags(paths)
    real = {}
    for p in paths:
        real[pre[p].get('File:FileType', '')] = real.get(pre[p].get('File:FileType', ''), 0) + 1
    print('real file types:', dict(sorted(real.items(), key=lambda x: -x[1])))
    jobs = [p for p in paths if pre[p].get('File:FileType') == 'JPEG']
    print(f'to try at q{Q}: {len(jobs)} '
          f'(skipped: {len(paths) - len(jobs)} whose real type is not JPEG)')
    if dry:
        print('DRY: nothing written')
        return
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, res in enumerate(ex.map(work, ((p, pre[p]) for p in jobs)), 1):
            results.append(res)
            if i % 400 == 0:
                print(f'  {i}/{len(jobs)}', flush=True)
    by = {}
    for r in results:
        by[r['status']] = by.get(r['status'], 0) + 1
    print('\nstatus counts:', by)
    done = [r for r in results if r['status'] == 'recompressed']
    bb = sum(r['bytes_before'] for r in done)
    ba = sum(r['bytes_after'] for r in done)
    vals = [r['psnr'] for r in done if r.get('psnr') is not None]
    print(f'recompressed {len(done)} files: {bb / 2**30:.2f} GiB -> {ba / 2**30:.2f} GiB '
          f'(-{(1 - ba / bb) * 100:.1f} %)')
    if vals:
        print(f'PSNR dB vs own original: min {min(vals):.1f}  median '
              f'{statistics.median(vals):.1f}  mean {statistics.mean(vals):.1f}  '
              f'floor {MIN_PSNR}')
    for r in results:
        if r['status'] not in ('recompressed', 'kept'):
            print('  PROBLEM', r['status'], r['new'], r.get('detail', ''))
    # fold the result back into the import manifest
    upd = {r['new']: r for r in results}
    for row in rows:
        r = upd.get(row['new'])
        if not r:
            continue
        if r['status'] == 'recompressed':
            row['bytes_after'] = str(r['bytes_after'])
            row['how'] = f'recompressed to q{Q}, EXIF/GPS re-injected, PSNR {r["psnr"]:.1f} dB'
        elif r['status'] == 'kept':
            row['how'] = f'moved in from the hhd source tree, bytes unchanged ({r["detail"]})'
        else:
            row['how'] = f'moved in from the hhd source tree, bytes unchanged ({r["status"]})'
    out_rows = rows_all if trees else rows
    with open(f'{W}/{man}', 'w', newline='', encoding='utf-8') as fh:
        wr = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        wr.writeheader()
        wr.writerows(out_rows)
    json.dump({'q': Q, 'min_save': MIN_SAVE, 'min_psnr': MIN_PSNR, 'counts': by,
               'bytes_before': bb, 'bytes_after': ba,
               'psnr': {'min': min(vals) if vals else None,
                        'median': statistics.median(vals) if vals else None,
                        'mean': statistics.mean(vals) if vals else None}},
              open(f'{W}/recompress-imports.json', 'w'), indent=1)
    print('manifest-imports.csv updated')


if __name__ == "__main__":
    main()
