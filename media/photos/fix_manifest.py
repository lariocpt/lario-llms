#!/usr/bin/env python3
"""Consistency fixes for manifest-moves.csv, using the hash index as arbiter.


  * swap the two PNGs that an earlier evidence-rank row cross-assigned: each new
    file is byte-identical to the other row's original, and no other unused
    original has that hash, so the pair is provably a straight swap.
  * recompute the change flag from real sizes. Nine hundred-odd rows inherited
    change=unchanged from an early pass while their sizes differ; a JPEG whose
    bytes changed was recompressed, whatever the earlier pass called it.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/fix_manifest.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
from collections import defaultdict
from paths import BACKUP, LIB

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass


def load(p):
    d = {}
    with open(p) as fh:
        for line in fh:
            r = json.loads(line)
            d[r['path']] = (r['size'], r['hash'])
    return d


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    hb = load(os.path.join(W, 'hashes_backup.jsonl'))
    hn = load(os.path.join(W, 'hashes_new.jsonl'))
    by_hash = defaultdict(list)
    for rel, (sz, h) in hb.items():
        if h:
            by_hash[h].append(rel)
    by_new = {r['new']: r for r in rows}
    holder = {r['orig']: r['new'] for r in rows}

    swapped = []
    for r in rows:
        h_n = hn.get(r['new'], (0, None))[1]
        if not h_n or h_n == hb.get(r['orig'], (0, None))[1]:
            continue
        if os.path.splitext(r['new'])[1].lower() in ('.jpg', '.jpeg'):
            continue                      # recompressed: a hash difference is expected
        for cand in by_hash.get(h_n, []):
            other = by_new.get(holder.get(cand, ''))
            if not other or other['new'] == r['new']:
                continue
            if hn.get(other['new'], (0, None))[1] == hb.get(r['orig'], (0, None))[1]:
                a_orig, b_orig = r['orig'], other['orig']
                for row, orig in ((r, cand), (other, r['orig'])):
                    row['orig'] = orig
                    row['orig_library'] = os.path.join(LIB, orig)
                    row['backup'] = os.path.join(BACKUP, orig)
                    row['bytes_before'] = str(hb[orig][0])
                    row['how'] = 'hash-swap'
                    row['folder'] = os.path.dirname(row['new'])
                swapped.append({'new_a': r['new'], 'orig_a': cand, 'was_a': a_orig,
                                'new_b': other['new'], 'orig_b': b_orig, 'was_b': other['orig']})
                break

    relabelled = 0
    for r in rows:
        sz_o = hb.get(r['orig'], (0,))[0]
        sz_n = hn.get(r['new'], (0,))[0]
        r['bytes_before'] = str(sz_o)
        r['bytes_after'] = str(sz_n)
        want = 'unchanged' if sz_o == sz_n else 'recompressed'
        if r['change'] != want:
            r['change'] = want
            relabelled += 1

    print(f'swapped pairs: {len(swapped)}')
    for s in swapped:
        print(f"  {s['new_a'][:50]}: {s['was_a']} -> {s['orig_a']}")
        print(f"  {s['new_b'][:50]}: {s['was_b']} -> {s['orig_b']}")
    print(f'change flags recomputed: {relabelled}')

    bad = [r for r in rows
           if not (hn.get(r['new'], (0, None))[1] == hb.get(r['orig'], (0, None))[1])
           and os.path.splitext(r['new'])[1].lower() not in ('.jpg', '.jpeg')]
    grew = [r for r in rows if int(r['bytes_after']) >= int(r['bytes_before'])
            and r['change'] == 'recompressed']
    print(f'non-JPEG rows still not byte-identical: {len(bad)}')
    print(f'recompressed rows that did not shrink: {len(grew)}')
    json.dump({'swapped': swapped, 'flags_relabelled': relabelled,
               'non_jpeg_mismatch': bad, 'did_not_shrink': grew},
              open(os.path.join(W, 'manifest-consistency.json'), 'w'), indent=1)
    if bad:
        print('NOT writing')
        return
    rows.sort(key=lambda r: r['new'])
    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print('manifest rewritten:', len(rows), 'rows')


if __name__ == "__main__":
    main()
