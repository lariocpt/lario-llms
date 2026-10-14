#!/usr/bin/env python3
"""Report-only scan for leftover near-duplicates in the reorganised library.


Two files are reported when ALL of these hold:
  * identical pixel dimensions after auto-orientation,
  * 4x4-block dHash (255 bits) within Hamming distance 6,
  * captured within 10 minutes of each other, or both under the same folder
    when neither has a usable capture time.

Nothing is deleted: the point is to show what a second, more aggressive pass
could remove and what that would be worth. Writes near-dups.json.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/find_neardups.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

W = '/home/lario/photos-reorg-work'
from paths import LIB
HASH_EXT = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.tif', '.tiff'}
ROTATE = {'5', '6', '7', '8'}


def walk_images():
    out = []
    for root, _dirs, names in os.walk(LIB):
        for n in names:
            if os.path.splitext(n)[1].lower() in HASH_EXT:
                out.append(os.path.join(root, n))
    return out


def batch_dims(files):
    """(w, h) after auto-orient, metadata only, in batches of 400 files."""
    dims = {}
    for i in range(0, len(files), 400):
        batch = files[i:i + 400]
        res = subprocess.run(
            ['exiftool', '-q', '-n', '-skipBinary', '-api', 'LargeFileSupport=1', '-json',
             '-ImageWidth', '-ImageHeight', '-Orientation', '--', *batch],
            capture_output=True, text=True).stdout
        for rec in json.loads(res or '[]'):
            try:
                w, h = int(float(rec['ImageWidth'])), int(float(rec['ImageHeight']))
            except (KeyError, TypeError, ValueError):
                continue
            if str(rec.get('Orientation', '')).split('=')[-1] in ROTATE:
                w, h = h, w
            dims[rec['SourceFile']] = (w, h)
    return dims


def dhash(path):
    """4x4-block difference hash over a 16x16 greyscale thumbnail (255 bits)."""
    try:
        raw = subprocess.run(['convert', path, '-auto-orient', '-resize', '16x16!',
                              '-colorspace', 'Gray', '-depth', '8', 'GRAY:-'],
                             capture_output=True, check=True).stdout
        rows = [raw[i * 16:i * 16 + 16] for i in range(16)]
        if any(len(r) != 16 for r in rows):
            return None
        h = 0
        for y in range(16):
            for x in range(15):
                h = (h << 1) | (1 if rows[y][x] > rows[y][x + 1] else 0)
        return h
    except Exception:
        return None


def main():
    moves = {}
    with open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            moves[os.path.join(LIB, r['new'])] = r

    files = walk_images()
    print(f'candidates: {len(files)}', flush=True)
    dm = batch_dims(files)
    print(f'dimensions resolved: {len(dm)}', flush=True)

    with ThreadPoolExecutor(max_workers=6) as ex:
        hashed = dict(zip(files, ex.map(dhash, files)))
    good = {p: h for p, h in hashed.items() if h is not None}
    print(f'dHash computed: {len(good)} (unreadable: {len(files) - len(good)})', flush=True)

    def ts(path):
        try:
            return datetime.strptime(moves[path]['dt'], '%Y-%m-%d %H:%M:%S').timestamp()
        except Exception:
            return None

    buckets = defaultdict(list)
    for p in good:
        buckets[dm.get(p)].append(p)

    pairs = []
    for dim, members in buckets.items():
        members.sort()
        for i, a in enumerate(members):
            ta = ts(a)
            for b in members[i + 1:]:
                tb = ts(b)
                if ta is not None and tb is not None:
                    if abs(ta - tb) > 600:
                        continue
                elif os.path.dirname(a) != os.path.dirname(b):
                    continue
                d = (good[a] ^ good[b]).bit_count()
                if d <= 6:
                    pairs.append({'a': os.path.relpath(a, LIB), 'b': os.path.relpath(b, LIB),
                                  'hamming': d, 'dims': list(dim) if dim else None,
                                  'bytes_a': os.path.getsize(a), 'bytes_b': os.path.getsize(b)})
    pairs.sort(key=lambda x: x['hamming'])

    # greedy clustering so the "worth" figure does not double-count a file twice
    owner, groups = {}, []
    for x in pairs:
        g = owner.get(x['a'], owner.get(x['b']))
        if g is None:
            groups.append([x['a'], x['b']])
            owner[x['a']] = owner[x['b']] = len(groups) - 1
        else:
            for p in (x['a'], x['b']):
                if p not in groups[g]:
                    groups[g].append(p)
                    owner[p] = g
    worth = 0
    for g in groups:
        sized = sorted((os.path.getsize(os.path.join(LIB, p)) for p in g), reverse=True)
        worth += sum(sized[1:])

    exact = exact_groups()
    with open(os.path.join(W, 'near-dups.json'), 'w') as f:
        json.dump({'pairs': pairs, 'groups': groups,
                   'removable_bytes_if_kept_biggest': worth,
                   'identical_bytes_groups': exact}, f, indent=1)
    print(f"\nnear-duplicate pairs: {len(pairs)}   clusters: {len(groups)}   "
          f"worth if the biggest of each is kept: {worth / 1e9:.2f} GB")
    print(f"byte-identical groups still present: {len(exact)}")
    for x in pairs[:20]:
        print(f"  d={x['hamming']:>2} {x['a'][-45:]}  <>  {x['b'][-45:]}")


def exact_groups():
    by = defaultdict(list)
    for root, _d, names in os.walk(LIB):
        for n in names:
            p = os.path.join(root, n)
            if os.path.getsize(p):
                by[os.path.getsize(p)].append(p)
    out = []
    for size, paths in by.items():
        if len(paths) < 2:
            continue
        hashes = defaultdict(list)
        for p in paths:
            with open(p, 'rb') as f:
                hashes[hashlib.blake2b(f.read(), digest_size=32).hexdigest()].append(p)
        for same in hashes.values():
            if len(same) > 1:
                out.append({'bytes': size,
                            'paths': sorted(os.path.relpath(p, LIB) for p in same)})
    return out


if __name__ == '__main__':
    main()
