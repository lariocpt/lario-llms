#!/usr/bin/env python3
"""Audit manifest-moves.csv against content hashes.


A row is only as good as its proof. Files that were never re-encoded (PNG, HEIC,
TIFF, NEF, GIF, and JPEGs left alone because recompressing them was not worth
it) are still byte-identical to their original, so hash(new) must equal
hash(orig) - if it does not, the row names the wrong original and the true one
is found by looking that hash up in the backup. Rows for recompressed JPEGs
cannot be hash-checked; they get dimensions, DateTimeOriginal, GPS and
orientation compared against the original in verify_meta.py instead.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/verify_manifest.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
from collections import Counter, defaultdict

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import LIB as NEW  # the live library, NOT the Photos.new staging tree
from paths import BACKUP as BK
RECOMPRESSIBLE = ('.jpg', '.jpeg')


def load_hashes(p):
    d = {}
    with open(p) as fh:
        for line in fh:
            r = json.loads(line)
            d[r['path']] = (r['size'], r['hash'])
    return d


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    hb = load_hashes(os.path.join(W, 'hashes_backup.jsonl'))
    hn = load_hashes(os.path.join(W, 'hashes_new.jsonl'))
    by_hash = defaultdict(list)
    for rel, (sz, h) in hb.items():
        if h:
            by_hash[h].append(rel)
    used = {r['orig'] for r in rows}
    # which new folder each old folder fed, according to the accepted rows
    lands = defaultdict(Counter)
    for r in rows:
        lands[os.path.dirname(r['orig'])][r['folder']] += 1

    ok = 0
    fixed, problems = [], []
    for r in rows:
        sz_n, h_n = hn.get(r['new'], (0, None))
        sz_o, h_o = hb.get(r['orig'], (0, None))
        if h_n and h_n == h_o:
            ok += 1
            if r['change'] != 'unchanged':
                r['change'] = 'unchanged'
            continue
        if os.path.splitext(r['new'])[1].lower() in RECOMPRESSIBLE:
            if int(r['bytes_after']) >= int(r['bytes_before']):
                problems.append({'new': r['new'], 'orig': r['orig'],
                                 'why': 'recompressed row that did not shrink'})
            continue
        # never re-encoded, so the named original has to be the same bytes
        alt = [o for o in by_hash.get(h_n, []) if o != r['orig']]
        free = [o for o in alt if o not in used]
        if free:
            pick = sorted(free, key=lambda o: (os.path.dirname(o) != os.path.dirname(r['orig']),
                                               os.path.dirname(alt[0]) if alt else '', o))[0]
            fixed.append({'new': r['new'], 'was': r['orig'], 'now': pick,
                          'how': r['how'], 'folder_votes_same_dir':
                              sum(1 for x in rows if x['orig'] == r['orig'])})
            used.discard(r['orig'])
            used.add(pick)
            r['orig'] = pick
            r['orig_library'] = os.path.join(NEW, pick)
            r['backup'] = os.path.join(BK, pick)
            r['bytes_before'] = str(hb[pick][0])
            r['how'] = 'hash-corrected'
            r['change'] = 'unchanged' if hb[pick][0] == sz_n else 'recompressed'
        else:
            problems.append({'new': r['new'], 'orig': r['orig'], 'how': r['how'],
                             'why': 'not byte-identical and no unused original has this hash',
                             'hash_in_backup': len(alt),
                             'cands': alt[:5]})

    print(f'rows {len(rows)}  hash-verified {ok}  corrected {len(fixed)}  problems {len(problems)}')
    for f in fixed[:20]:
        print(f"  corrected {f['new'][:52]}\n      was {f['was'][:56]}\n      now {f['now'][:56]}")
    for p in problems[:20]:
        print(f"  PROBLEM {p['new'][:56]}  [{p['why']}]  cands={p.get('cands')}")

    dup_new = [k for k, v in Counter(r['new'] for r in rows).items() if v > 1]
    dup_orig = [k for k, v in Counter(r['orig'] for r in rows).items() if v > 1]
    print(f'dup new {len(dup_new)}  dup orig {len(dup_orig)}')
    json.dump({'hash_corrected': fixed, 'problems': problems},
              open(os.path.join(W, 'manifest-hash-audit.json'), 'w'), indent=1)
    if not dup_new and not dup_orig:
        rows.sort(key=lambda r: r['new'])
        with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print('manifest rewritten')


if __name__ == "__main__":
    main()
