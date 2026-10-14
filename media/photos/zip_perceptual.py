#!/usr/bin/env python3
"""Perceptual check of the staged archive images against the live library.


Byte hashes are already settled (classify_zips.py). This is the second net: a
photo that was resaved, cropped or re-exported at some point has different bytes
but the same picture. 16x16 dHash distance <= 2 is a candidate; the candidate is
only ever dropped when decoding both files gives RMSE exactly 0, i.e. identical
pixels. Everything else is kept, with its number recorded.

Writes zip-pixel-hits.json (every candidate and its verdict) and, when there is
anything to drop, appends it to pixel-verdicts.json in the same shape the loose
import used, then rewrites new-candidates-zips.json and zip-ledger.csv without
the dropped entries.

usage: python3 zip_perceptual.py [--apply]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/zip_perceptual.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

W = '/home/lario/photos-reorg-work'
from paths import LIB
from paths import VIDLIB
MAXDIST = 2


def ham(a, b):
    return (int(a, 16) ^ int(b, 16)).bit_count()


def load(fn):
    out = []
    for line in open(f'{W}/{fn}'):
        d = json.loads(line)
        out.append(d)
    return out


def orient(path):
    """Auto-oriented copy for pixel comparison (the library keeps orientation
    tags rather than rotating, and a rotated twin would otherwise look different)."""
    os.makedirs('/tmp/opencode/pixcmp', exist_ok=True)
    out = '/tmp/opencode/pixcmp/%s.png' % abs(hash((path, os.path.getmtime(path))))
    if not os.path.exists(out):
        subprocess.run(['magick', path, '-auto-orient', out], capture_output=True)
        if not os.path.exists(out):
            return path            # undecodable: compare as-is and let RMSE fail loud
    return out


def rmse(a, b):
    pa, pb = orient(a), orient(b)
    r = subprocess.run(['magick', 'compare', '-metric', 'RMSE', pa, pb, 'null:'],
                       capture_output=True, text=True)
    m = re.search(r'\(([\d.e+-]+)\)', r.stderr or '')
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def main():
    apply_ = '--apply' in sys.argv
    roots = json.load(open(f'{W}/zip-roots.json'))['roots']
    live = load('dhash_live_now.jsonl')
    cand = load('dhash_zips.jsonl')
    print(f'{len(cand)} staged images against {len(live)} live pictures')
    # bucket live hashes by 16-bit slices: a hash within distance 2 must match
    # at least one slice exactly, so only those pairs are compared
    buckets = [defaultdict(list) for _ in range(4)]
    for i, d in enumerate(live):
        bits = int(d['dhash'], 16)
        for k in range(4):
            buckets[k][(bits >> (64 * k)) & ((1 << 64) - 1)].append(i)
    hits = []
    for c in cand:
        bits = int(c['dhash'], 16)
        seen = set()
        for k in range(4):
            for j in buckets[k][(bits >> (64 * k)) & ((1 << 64) - 1)]:
                seen.add(j)
        best = None
        for j in seen:
            d = ham(c['dhash'], live[j]['dhash'])
            if d <= MAXDIST and (best is None or d < best[0]):
                best = (d, live[j])
        if best:
            hits.append({'file': c['path'], 'dhash_dist': best[0],
                         'against': best[1]['path']})
    print(f'{len(hits)} perceptual candidates at distance <= {MAXDIST}')
    for h in hits:
        h['rmse'] = rmse(h['file'], h['against'])
        h['verdict'] = ('drop-pixel-identical' if h['rmse'] == 0.0
                        else 'keep-different-pixels')
        print(f"  {h['rmse']:.5f} d={h['dhash_dist']} "
              f"{os.path.relpath(h['file'], W)[-52:]} vs {h['against'][-52:]} "
              f"-> {h['verdict']}")
    json.dump(hits, open(f'{W}/zip-pixel-hits.json', 'w'), indent=1)
    drops = [h for h in hits if h['verdict'] == 'drop-pixel-identical']
    if not drops:
        print('\nnothing to drop: every perceptual candidate differs in pixels')
        return
    if not apply_:
        print(f'\n{len(drops)} pixel-identical, not applied (pass --apply)')
        return

    pv = json.load(open(f'{W}/pixel-verdicts.json'))
    have = {(d['tree'], d['rel']) for d in pv['drop_pixel_identical']}
    staged_root = os.path.realpath(f'{W}/zip-extract')
    for h in drops:
        rel_root = os.path.relpath(os.path.realpath(h['file']), staged_root)
        tag, _, rel = rel_root.partition('/')
        rec = {'tree': tag, 'rel': rel, 'rmse': 0.0,
               'against': os.path.relpath(h['against'], LIB if h['against'].startswith(
                   LIB) else VIDLIB),
               'note': 'archive entry, dHash distance %d, pixels identical to a '
                       'picture already in the library' % h['dhash_dist']}
        if (tag, rel) not in have:
            pv['drop_pixel_identical'].append(rec)
            have.add((tag, rel))
    json.dump(pv, open(f'{W}/pixel-verdicts.json', 'w'), indent=1)

    dropped = {(r['tree'], r['rel']) for r in pv['drop_pixel_identical']}
    rows = list(csv.DictReader(open(f'{W}/zip-ledger.csv', encoding='utf-8')))
    for r in rows:
        if (r['tag'], r['staged_rel']) in dropped and r['status'] == 'new-image':
            r['status'] = 'dup-live-perceptual'
            r['proof'] = next(h['against'] for h in drops
                              if os.path.realpath(h['file']) ==
                              os.path.realpath(os.path.join(roots[r['tag']],
                                                            r['staged_rel'])))
    rows.sort(key=lambda r: (r['status'], -int(r['bytes'])))
    with open(f'{W}/zip-ledger.csv', 'w', newline='', encoding='utf-8') as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    cand = json.load(open(f'{W}/new-candidates-zips.json'))
    for key in ('new-image', 'new-video'):
        cand[key] = [x for x in cand[key] if (x[0], x[1]) not in dropped]
    json.dump(cand, open(f'{W}/new-candidates-zips.json', 'w'), indent=1)
    print(f'dropped {len(drops)} archive entries as pixel-identical; '
          f'candidates now {len(cand["new-image"])} images / {len(cand["new-video"])} videos')


if __name__ == "__main__":
    main()
