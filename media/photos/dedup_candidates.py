#!/usr/bin/env python3
"""Which candidate photos are the same shot as something already in the library.


Byte-hashes already caught the exact matches (analyze_sources.py). This catches
the same picture re-rendered: same oriented dimensions, dHash within Hamming 6,
capture time within 10 minutes - the same rule find_neardups.py uses, applied
candidate -> live library, and candidate -> candidate across the two source trees.

Writes dedup-candidates.json. Report only.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/dedup_candidates.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime

W = '/home/lario/photos-reorg-work'
from paths import LIB
GB = 'photos/Grant Backup'          # archived intact, never imported
DATE_SRC = ['EXIF:DateTimeOriginal', 'EXIF:DateTimeDigitized', 'IFD0:DateTimeOriginal',
            'XMP:DateCreated', 'XMP:CreateDate', 'ExifIFD:DateTimeOriginal',
            'File:FileModifyDate']
ROTATE = {'5', '6', '7', '8'}


def getd(rec):
    for t in DATE_SRC:
        v = rec.get(t)
        if isinstance(v, list):
            v = v[0]
        if v:
            m = re.match(r'(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})',
                         str(v).replace('T', ' '))
            if m:
                s = '-'.join(m.groups()[:3]) + ' ' + ':'.join(m.groups()[3:])
                if s > '2000-01-01':
                    return s
    return None


def getdims(rec):
    sz = rec.get('Composite:ImageSize') or ''
    if isinstance(sz, list):
        sz = sz[0]
    m = re.match(r'(\d+)x(\d+)', str(sz)) if sz else None
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    else:
        w = rec.get('File:ImageWidth')
        h = rec.get('File:ImageHeight')
        if not (w and h):
            return None
        w, h = int(str(w).split()[0]), int(str(h).split()[0])
    o = str(rec.get('IFD0:Orientation') or rec.get('EXIF:Orientation') or '1').split('=')[-1].strip()
    return (h, w) if o in ROTATE else (w, h)


def load_jsonl(fn, key='path'):
    out = {}
    for line in open(os.path.join(W, fn)):
        d = json.loads(line)
        out[d[key]] = d
    return out


def main():
    cand_meta = load_jsonl('meta_cand.jsonl', 'SourceFile')
    cand_hash = load_jsonl('dhash_cand.jsonl')
    live_hash = load_jsonl('dhash_live.jsonl')
    live_dt = {}
    with open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            live_dt[os.path.join(LIB, r['new'])] = r['dt']

    def rot(p):
        rec = cand_meta.get(p, {})
        o = str(rec.get('IFD0:Orientation') or '1').split('=')[-1].strip()
        return o in ROTATE

    # live index: oriented dims -> [(dt, hash, path)]
    live = defaultdict(list)
    for p, d in live_hash.items():
        w, h = d['w'], d['h']
        # live files keep their orientation tag; dhash was computed auto-oriented,
        # so bucket by the un-rotated pair and let the time check do the rest
        live[(w, h)].append((live_dt.get(p), d['dhash'], p))

    cand = []
    for p, d in cand_hash.items():
        rel = None
        for tag, root in (('Mac Photos', 'Mac Photos'), ('Photosusa', 'Photosusa')):
            if f'/{root}/' in p:
                rel = p.split(f'/{root}/', 1)[1]
                src = tag
        if rel is None or os.path.basename(p).startswith('._'):
            continue
        rec = cand_meta.get(p, {})
        cand.append({'path': p, 'rel': rel, 'src': src,
                     'grant': rel.startswith(GB),
                     'ext': os.path.splitext(p)[1].lower(),
                     'bytes': os.path.getsize(p) if os.path.exists(p) else 0,
                     'dt': getd(rec), 'dims': (d['w'], d['h']),
                     'rot': rot(p), 'dhash': d['dhash'],
                     'gps': bool(rec.get('EXIF:GPSLatitude') or rec.get('GPS:GPSLatitude'))})

    img = [c for c in cand if c['ext'] in ('.jpg', '.jpeg', '.png', '.tif', '.tiff')]

    def ham(a, b):
        return (int(a, 16) ^ int(b, 16)).bit_count()

    out = {'dup_live': [], 'dup_live_needs_time': [], 'dup_between_sources': [],
           'unique': []}
    for c in img:
        best = None
        for ldt, lh, lp in live.get((c['dims'][0], c['dims'][1]), []):
            d = ham(c['dhash'], lh)
            if d > 6:
                continue
            near = False
            if c['dt'] and ldt:
                t1 = datetime.strptime(c['dt'], '%Y-%m-%d %H:%M:%S').timestamp()
                t0 = datetime.strptime(ldt, '%Y-%m-%d %H:%M:%S').timestamp()
                near = abs(t1 - t0) <= 600
            if best is None or d < best[0]:
                best = (d, lp, ldt, near)
        if best and best[3]:
            out['dup_live'].append({**{k: c[k] for k in
                                 ('path', 'rel', 'src', 'bytes', 'dt', 'ext', 'grant')},
                                 'live': os.path.relpath(best[1], LIB), 'hamming': best[0],
                                 'live_dt': best[2]})
        elif best:
            out['dup_live_needs_time'].append({**{k: c[k] for k in
                                            ('path', 'rel', 'src', 'bytes', 'dt', 'ext', 'grant')},
                                            'live': os.path.relpath(best[1], LIB),
                                            'hamming': best[0], 'live_dt': best[2]})
        else:
            out['unique'].append(c['path'])

    # candidate vs candidate (same dims + hash distance + 10 min window)
    by_dims = defaultdict(list)
    for c in img:
        by_dims[c['dims']].append(c)
    seen = set()
    for members in by_dims.values():
        members.sort(key=lambda c: c['dt'] or '0000')
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if b['src'] == a['src']:
                    continue
                if ham(a['dhash'], b['dhash']) > 6:
                    continue
                if a['dt'] and b['dt']:
                    t1 = datetime.strptime(a['dt'], '%Y-%m-%d %H:%M:%S').timestamp()
                    t0 = datetime.strptime(b['dt'], '%Y-%m-%d %H:%M:%S').timestamp()
                    if abs(t1 - t0) > 600:
                        continue
                key = (a['path'], b['path'])
                if key in seen:
                    continue
                seen.add(key)
                out['dup_between_sources'].append({
                    'a': a['rel'], 'a_src': a['src'], 'a_bytes': a['bytes'], 'a_grant': a['grant'],
                    'b': b['rel'], 'b_src': b['src'], 'b_bytes': b['bytes'], 'b_grant': b['grant'],
                    'hamming': ham(a['dhash'], b['dhash'])})

    def tot(rows, k='bytes'):
        return sum(r[k] for r in rows) / 1e9
    print(f"candidates (images, dHashed): {len(img)}   incl. Grant Backup: {sum(1 for c in img if c['grant'])}")
    print(f"same shot already in the library      : {len(out['dup_live']):5d}  {tot(out['dup_live']):6.2f} GB")
    print(f"   looks same but capture time differs: {len(out['dup_live_needs_time']):5d}  {tot(out['dup_live_needs_time']):6.2f} GB")
    print(f"same picture in both source trees     : {len(out['dup_between_sources']):5d} pairs")
    print(f"unique                                : {len(out['unique']):5d}  "
          f"{sum(os.path.getsize(p) for p in out['unique'])/1e9:6.2f} GB")
    json.dump(out, open(os.path.join(W, 'dedup-candidates.json'), 'w'), indent=1)
    print('wrote dedup-candidates.json')


if __name__ == '__main__':
    main()
