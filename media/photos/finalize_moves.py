#!/usr/bin/env python3
"""Close out manifest-moves.csv.


Step 1 - one row per new path. The second rebuild_moves5 run re-assigned rows
from the stale moves_unresolved4.json, so 26 new paths carry two different
originals. Where they disagree, content proof wins over metadata ranking, which
wins over ordering/perceptual guesses: a byte-hash match is decisive, a
same-dimensions or perceptual match is only an inference.

Step 2 - the new paths that still have no original. Pick from the unused
originals with the same extension and pixel dimensions (a recompressed JPEG
keeps its dimensions), ranked by which old folder the folder map says lands in
this new folder; when several are equally plausible, compare 16x16 dHash of the
survivor against each candidate and accept only a clear winner. Anything else
is written to moves_ambiguous.json instead of being guessed.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/finalize_moves.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
from collections import Counter, defaultdict

W = '/home/lario/photos-reorg-work'
from paths import BACKUP as BK
from paths import STAGING as NEW
from paths import LIB as OLD
JPEGISH = {'jpg', 'jpeg', 'jpe'}
RAWS = {'nef', 'cr2', 'cr3', 'arw', 'raf', 'dng', 'orf', 'rw2'}
# lower rank = stronger proof
HOW_RANK = {'global-hash': 0, 'global-hash-duplicates': 1, 'dims-unique': 2,
            'perceptual-d0': 3, 'perceptual-d1': 3, 'perceptual-d2': 3,
            'perceptual-d3': 3, 'perceptual-d4': 3, 'perceptual-only-d0': 3,
            'folder+date+dims': 4, 'folder+date': 5, 'evidence-rank': 6,
            '+size': 7, 'size-plausible': 8, 'undated-stem': 9,
            'undated-stem2': 9, 'date+order': 10, 'order-zip': 11}
TS = re.compile(r'(?:^|_)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')


def norm(d):
    return {k.lower(): v for k, v in d.items()}


def dims_of(m):
    mm = re.match(r'(\d+)x(\d+)', str(m.get('composite:imagesize') or ''))
    return (int(mm.group(1)), int(mm.group(2))) if mm else None


def ext_of(p):
    e = os.path.splitext(p)[1][1:].lower()
    return 'jpg' if e in JPEGISH else e


def kind_of(e):
    if e in RAWS:
        return 'raw'
    if e in ('jpg', 'png', 'heic', 'gif', 'tif', 'tiff', 'bmp', 'webp'):
        return 'image'
    return 'other'


def ts(rel):
    mm = TS.search(os.path.basename(rel))
    return (f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} '
            f'{mm.group(4)}:{mm.group(5)}:{mm.group(6)}') if mm else ''


def load_hashes(p):
    out = {}
    with open(p) as fh:
        for line in fh:
            r = json.loads(line)
            out[r['path']] = (r['size'], r['hash'])
    return out


def dhash(path, size=16):
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert('L').resize((size + 1, size))
    px = list(im.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (1 if px[row * (size + 1) + col] > px[row * (size + 1) + col + 1] else 0)
    return bits


def ham(a, b):
    return bin(a ^ b).count('1')


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    unresolved = json.load(open(os.path.join(W, 'moves_unresolved5.json')))
    hb = load_hashes(os.path.join(W, 'hashes_backup.jsonl'))
    hn = load_hashes(os.path.join(W, 'hashes_new.jsonl'))
    nfiles = set(hn)

    # ---- step 1: one row per new path, strongest proof wins -----------------
    by_new = defaultdict(list)
    for r in rows:
        by_new[r['new']].append(r)

    def rank(r):
        base = re.sub(r'-d\d+$', '', r['how'])
        return (HOW_RANK.get(base, 12), HOW_RANK.get(r['how'], 12), r['orig'])

    final, conflicts = [], []
    for new, cand in by_new.items():
        cand.sort(key=rank)
        final.append(cand[0])
        if len(cand) > 1:
            conflicts.append({'new': new, 'kept': cand[0]['orig'], 'kept_how': cand[0]['how'],
                              'dropped': [{'orig': c['orig'], 'how': c['how']} for c in cand[1:]]})
    print(f'rows in: {len(rows)}  unique new paths: {len(final)}  conflicts resolved: {len(conflicts)}')
    for c in sorted(conflicts, key=lambda c: c['new'])[:8]:
        print(f"  {c['new']}\n    kept {c['kept_how']:24s} {c['kept'][:60]}")
        for d in c['dropped']:
            print(f"    drop {d['how']:24s} {d['orig'][:60]}")

    # ---- step 2: close what is still open -----------------------------------
    used = {r['orig'] for r in final}
    open_new = [x for x in unresolved if x not in by_new or len(by_new[x]) == 0]
    open_new = [x for x in open_new if x not in {r['new'] for r in final}]
    print('new paths with no original:', len(open_new))

    meta_new = json.load(open(os.path.join(W, 'meta_new.json')))
    # which old folder each new folder drew its files from, per the accepted map
    lands = defaultdict(Counter)
    for r in final:
        lands[os.path.dirname(r['orig'])][r['folder']] += 1

    unused = [o for o in hb if o not in used]
    by_ext_dims = defaultdict(list)
    recs = json.load(open(os.path.join(W, 'meta_backup_dates.json')))
    bak = {}
    for r in recs:
        src = r.get('SourceFile')
        if not src:
            continue
        rel = os.path.relpath(src, BK)
        m = norm(r)
        bak[rel] = dict(ext=ext_of(rel), dims=dims_of(m), junk=(
            os.path.basename(rel).startswith('._') or os.path.basename(rel) == '.DS_Store'
            or rel.lower().endswith('.aae')))
    for o in unused:
        b = bak.get(o)
        if not b or b['junk']:
            continue
        by_ext_dims[(b['ext'], b['dims'])].append(o)

    closed, ambiguous = [], []
    for rel in sorted(open_new):
        nd = dims_of(norm(meta_new[rel])) if rel in meta_new else None
        ext = ext_of(rel)
        folder = os.path.dirname(rel)
        pool = by_ext_dims.get((ext, nd), [])
        if not pool:
            ambiguous.append({'new': rel, 'why': 'no unused original with same ext+dims',
                              'ext': ext, 'dims': 'x'.join(map(str, nd)) if nd else None,
                              'bytes': hn.get(rel, (0,))[0]})
            continue
        pool = sorted(pool, key=lambda o: lands[os.path.dirname(o)].get(folder, 0), reverse=True)
        pick, how, note = None, None, None
        if len(pool) == 1:
            pick, how = pool[0], 'dims-unique-final'
        else:
            votes = [lands[os.path.dirname(o)].get(folder, 0) for o in pool]
            top = sorted(set(votes), reverse=True)
            tied = [o for o, v in zip(pool, votes) if v == top[0]] if top[0] > 0 else pool
            if len(tied) == 1:
                pick, how = tied[0], 'evidence-unique-final'
            else:
                try:
                    nh = dhash(os.path.join(NEW, rel))
                except Exception as e:
                    ambiguous.append({'new': rel, 'why': f'unreadable survivor: {e}',
                                      'cands': tied[:20]})
                    continue
                scored = []
                for o in tied[:40]:
                    try:
                        scored.append((ham(nh, dhash(os.path.join(BK, o))), o))
                    except Exception:
                        continue
                scored.sort()
                if len(scored) == 1:
                    pick, how = scored[0][1], f'perceptual-only-d{scored[0][0]}'
                elif scored and scored[0][0] <= 8 and scored[0][0] + 8 <= scored[1][0]:
                    pick, how = scored[0][1], f'perceptual-d{scored[0][0]}'
                    note = f'margin {scored[1][0] - scored[0][0]} over runner-up {scored[1][1]}'
                else:
                    ambiguous.append({'new': rel, 'why': 'perceptual match not decisive',
                                      'cands': [{'orig': o, 'd': d} for d, o in scored[:6]]})
                    continue
        if pick is None:
            ambiguous.append({'new': rel, 'why': 'several equally-plausible originals',
                              'cands': pool[:20]})
            continue
        if pick in used:
            ambiguous.append({'new': rel, 'why': 'only candidate already used', 'cands': [pick]})
            continue
        size_new = hn.get(rel, (0,))[0]
        final.append({'new': rel, 'orig': pick, 'orig_library': os.path.join(OLD, pick),
                      'backup': os.path.join(BK, pick), 'kind': kind_of(bak[pick]['ext']),
                      'change': 'unchanged' if hb[pick][0] == size_new else 'recompressed',
                      'bytes_before': str(hb[pick][0]), 'bytes_after': str(size_new),
                      'how': how, 'dt': ts(rel), 'folder': folder})
        used.add(pick)
        closed.append({'new': rel, 'orig': pick, 'how': how, 'note': note})

    print('closed now:', len(closed))
    for c in closed:
        print(f"  {c['how']:26s} {c['orig'][:58]} -> {c['new'][:52]}")
    print('still ambiguous:', len(ambiguous))
    for a in ambiguous:
        print(f"  {a['new']}  [{a['why']}]")

    # ---- checks + write ----------------------------------------------------
    new_set = set(r['new'] for r in final)
    missing = sorted(nfiles - new_set)
    extra = sorted(new_set - nfiles)
    dup_new = [k for k, v in Counter(r['new'] for r in final).items() if v > 1]
    dup_orig = [k for k, v in Counter(r['orig'] for r in final).items() if v > 1]
    missing_rows = [r['new'] for r in final if not os.path.exists(os.path.join(NEW, r['new']))]
    missing_orig = [r['orig'] for r in final if not os.path.exists(os.path.join(BK, r['orig']))]
    print(f'files not covered: {len(missing)}  rows for absent files: {len(extra)}  '
          f'dup new: {len(dup_new)}  dup orig: {len(dup_orig)}  '
          f'absent new: {len(missing_rows)}  absent orig: {len(missing_orig)}')
    for m in missing[:10]:
        print('   uncovered:', m)

    json.dump({'conflicts_resolved': conflicts, 'closed_final': closed,
               'ambiguous': ambiguous, 'uncovered': missing},
              open(os.path.join(W, 'moves-final-audit.json'), 'w'), indent=1)
    if dup_new or dup_orig or extra or missing_rows or missing_orig:
        print('NOT writing: integrity check failed')
        return
    final.sort(key=lambda r: r['new'])
    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(final)
    print('manifest rows written:', len(final))
    print('methods:', Counter(r['how'] for r in final).most_common(20))


if __name__ == "__main__":
    main()
