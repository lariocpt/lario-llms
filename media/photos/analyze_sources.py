#!/usr/bin/env python3
"""Classify the two new source trees against the live library.


Reads the BLAKE2b indexes (hashes_macphotos.jsonl, hashes_photosusa.jsonl) and
answers: how much of this is already in ~/Pictures/Photos, in what form, and
what would actually be new. Report only - it moves nothing.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/analyze_sources.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
from paths import HHD

import collections
import csv
import json
import os

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
SRC = {
    # both trees sit under the one drive root core/config.py calls HHD
    'Mac Photos': ('hashes_macphotos.jsonl', os.path.join(HHD, 'Mac Photos')),
    'Photosusa': ('hashes_photosusa.jsonl', os.path.join(HHD, 'Photosusa')),
}
IMG = {'jpg', 'jpeg', 'heic', 'png', 'tif', 'tiff', 'gif', 'nef', 'cr2', 'dng'}
VID = {'mov', 'mp4', 'avi', '3gp', 'mpg', 'mpeg', 'dv', 'vob', 'm4v', 'wmv', 'flv', 'mts'}
JUNKNAME = {'Thumbs.db', 'desktop.ini', '.DS_Store', 'lrcat', 'lrprev', 'db', 'zip',
            'psd', 'ini', 'txt', 'pdf', 'ifo', 'bup', 'aae'}


def load(fn):
    out = []
    with open(os.path.join(W, fn)) as fh:
        for line in fh:
            d = json.loads(line)
            out.append((d['hash'], d['path'], d['size']))
    return out


def kind(ext):
    e = ext.lower().lstrip('.')
    if e in IMG:
        return 'image'
    if e in VID:
        return 'video'
    if e in JUNKNAME:
        return 'other:' + e
    return 'other:' + e


def main():
    live = {}
    for fn in ('hashes_new.jsonl', 'hashes_livevideos.jsonl'):
        for h, p, s in load(fn):
            live[h] = (fn, p)
    orig = {}
    for h, p, s in load('hashes_backup.jsonl'):
        orig.setdefault(h, []).append(p)
    # which originals are represented live now (survivors, whatever bytes they have)
    survivors = {}
    with open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            for k in ('orig', 'backup'):
                if r.get(k):
                    survivors[r[k]] = r['new']
    deleted = set()
    with open(os.path.join(W, 'manifest-deletes.csv'), encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            deleted.add(r['orig'])
            if r.get('backup'):
                deleted.add(r['backup'])

    seen = set()
    stats = collections.defaultdict(lambda: [0, 0])
    detail = collections.defaultdict(lambda: collections.Counter())
    buckets = collections.defaultdict(list)
    for tag, (fn, root) in SRC.items():
        for h, rel, size in load(fn):
            ext = os.path.splitext(rel)[1]
            k = kind(ext)
            key = h
            if key in seen:
                stats['dup between the two source trees'][:] = [
                    stats['dup between the two source trees'][0] + 1,
                    stats['dup between the two source trees'][1] + size]
                continue
            seen.add(h)
            if h in live:
                label = 'already live, byte-identical'
            elif h in orig:
                ops = orig[h]
                if any(o in survivors for o in ops):
                    label = 'same content already live (recompressed twin)'
                elif any(o in deleted for o in ops):
                    label = 'matches an original we deleted as duplicate'
                else:
                    label = 'matches an original, resolution unknown'
                    buckets['unknown-original'].append((tag, rel, size))
                    detail[tag + ' ' + label][k] += 1
                    stats[label][0] += 1
                    stats[label][1] += size
                    continue
            else:
                label = 'NEW (no hash match anywhere)'
                buckets['new-' + k].append((tag, rel, size))
            detail[tag + ' ' + label][k] += 1
            stats[label][0] += 1
            stats[label][1] += size

    print(f'{"category":48s} {"files":>7s} {"GB":>8s}')
    for k, (n, b) in sorted(stats.items(), key=lambda x: -x[1][1]):
        print(f'{k:48s} {n:7d} {b/1e9:8.2f}')
    print()
    print('--- by source / category / kind')
    for k, c in sorted(detail.items()):
        print(f'{k:60s} ' + ' '.join(f'{kk}={vv}' for kk, vv in c.most_common(8)))
    print()
    print('--- NEW files, kind totals')
    for k in sorted(buckets):
        if k == 'unknown-original':
            continue
        rows = buckets[k]
        print(f'{k:22s} {len(rows):6d} files  {sum(r[2] for r in rows)/1e9:7.2f} GB')
    with open(os.path.join(W, 'new-candidates.json'), 'w') as fh:
        json.dump({k: [list(r) for r in v] for k, v in buckets.items()}, fh, indent=1)
    print('\nwrote new-candidates.json')


if __name__ == '__main__':
    main()
