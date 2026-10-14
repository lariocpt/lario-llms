#!/usr/bin/env python3
"""Last moves rows, decided by content.


Global hash: files that were never re-encoded (PNG/HEIC/TIFF/NEF, and JPEGs that
were too small to be worth recompressing) are byte-identical to their original, so
a hash match anywhere in the still-unused backup is proof, not a guess.

Dimensions-unique / perceptual: for recompressed JPEGs, narrow the unused originals
to the ones with the same pixel dimensions and, when several remain, compare a
16x16 dHash of the survivor with each candidate and keep a clear winner.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rebuild_moves5.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
from collections import Counter, defaultdict

W = '/home/lario/photos-reorg-work'
BK = '/mnt/xfs/photos-originals-backup'
NEW = '/home/lario/Pictures/Photos.new'
OLD = '/home/lario/Pictures/Photos'
JPEGISH = {'jpg', 'jpeg', 'jpe'}
RAWS = {'nef', 'cr2', 'cr3', 'arw', 'raf', 'dng', 'orf', 'rw2'}
DATE_CHAIN = ['exif:datetimeoriginal', 'exififd:datetimeoriginal', 'ifd0:datetimeoriginal',
              'xmp:datetimecreated', 'xmp:datecreated', 'xmp:createdate', 'xmp:modifydate',
              'exif:createdate', 'exififd:createdate', 'ifd0:createdate', 'ifd0:datetime',
              'quicktime:createdate', 'quicktime:trackcreatedate', 'composite:datetimecreated',
              'file:filemodifydate', 'system:filemodifydate', 'file:filecreatedate']
TS = re.compile(r'(?:^|_)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')


def norm(d):
    return {k.lower(): v for k, v in d.items()}


def date_of(m):
    for k in DATE_CHAIN:
        v = m.get(k)
        if v:
            s = str(v)[:19].replace('T', ' ')
            mm = re.match(r'(\d{4})-(\d{2})-(\d{2})[ T](\d{2})[:.](\d{2})[:.](\d{2})', s)
            if mm:
                return f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} {mm.group(4)}:{mm.group(5)}:{mm.group(6)}'
    return None


def dims_of(m):
    mm = re.match(r'(\d+)x(\d+)', str(m.get('composite:imagesize') or ''))
    if mm:
        return int(mm.group(1)), int(mm.group(2))
    return None


def ext_of(p, m):
    e = (m.get('file:filetypeextension') or os.path.splitext(p)[1][1:]).lower()
    return 'jpg' if e in JPEGISH else e


def kind_of(e):
    if e in RAWS:
        return 'raw'
    if e in ('jpg', 'png', 'heic', 'gif', 'tif', 'tiff', 'bmp', 'webp'):
        return 'image'
    return 'other'


def is_junk(name):
    return name.startswith('._') or name == '.DS_Store' or name.lower().endswith('.aae')


def ts(rel):
    mm = TS.search(os.path.basename(rel))
    return (f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} '
            f'{mm.group(4)}:{mm.group(5)}:{mm.group(6)}') if mm else None


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


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    open_rows = json.load(open(os.path.join(W, 'moves_unresolved4.json')))
    used = {r['orig'] for r in rows}
    hb = load_hashes(os.path.join(W, 'hashes_backup.jsonl'))
    hn = load_hashes(os.path.join(W, 'hashes_new.jsonl'))
    recs = json.load(open(os.path.join(W, 'meta_backup_dates.json')))
    bak = {}
    for r in recs:
        src = r.get('SourceFile')
        if not src:
            continue
        rel = os.path.relpath(src, BK)
        m = norm(r)
        bak[rel] = dict(ext=ext_of(rel, m), dims=dims_of(m), date=(date_of(m) or '')[:10],
                        junk=is_junk(os.path.basename(rel)))
    free = lambda rel: rel not in used and rel in bak and not bak[rel]['junk']

    hash_to_unused = defaultdict(list)
    for rel, (size, h) in hb.items():
        if free(rel) and h:
            hash_to_unused[h].append(rel)

    lands = defaultdict(Counter)
    for r in rows:
        lands[os.path.dirname(r['orig'])][r['folder']] += 1

    def assign(rel, orig, how):
        size_new = hn.get(rel, (0, None))[0]
        rows.append({'new': rel, 'orig': orig, 'orig_library': os.path.join(OLD, orig),
                     'backup': os.path.join(BK, orig), 'kind': kind_of(bak[orig]['ext']),
                     'change': 'unchanged' if hb[orig][0] == size_new else 'recompressed',
                     'bytes_before': str(hb[orig][0]), 'bytes_after': str(size_new),
                     'how': how, 'dt': ts(rel) or '', 'folder': os.path.dirname(rel)})
        used.add(orig)
        for h2 in ([hb[orig][1]] if hb[orig][1] else []):
            hash_to_unused[h2] = [o for o in hash_to_unused[h2] if o != orig]

    rows_before = len(rows)
    still = []
    for rel in open_rows:
        h = hn.get(rel, (0, None))[1]
        hits = hash_to_unused.get(h, []) if h else []
        if len(hits) == 1:
            assign(rel, hits[0], 'global-hash')
        elif len(hits) > 1:
            assign(rel, sorted(hits)[0], 'global-hash-duplicates')
        else:
            still.append(rel)

    # recompressed survivors: same pixel dimensions among the unused originals
    nmeta = json.load(open(os.path.join(W, 'meta_new.json')))
    for rel in list(still):
        nd = dims_of(norm(nmeta[rel])) if rel in nmeta else None
        ext = ext_of(rel, {})
        folder = os.path.dirname(rel)
        pool = [o for lst in hash_to_unused.values() for o in lst if free(o)]
        cand = [o for o in pool if bak[o]['ext'] == ext and (not nd or bak[o]['dims'] == nd)]
        if len(cand) == 1:
            assign(rel, cand[0], 'dims-unique')
            still.remove(rel)
            continue
        if not cand:
            continue
        cand.sort(key=lambda o: lands[os.path.dirname(o)].get(folder, 0), reverse=True)
        cand = cand[:40]
        try:
            nh = dhash(os.path.join(NEW, rel))
        except Exception:
            continue
        scored = []
        for o in cand:
            try:
                scored.append((dham(nh, dhash(os.path.join(BK, o))), o))
            except Exception:
                continue
        if not scored:
            continue
        scored.sort()
        if len(scored) == 1:
            assign(rel, scored[0][1], f'perceptual-only-d{scored[0][0]}')
            still.remove(rel)
        elif scored[0][0] <= 10 and scored[0][0] + 6 <= scored[1][0]:
            assign(rel, scored[0][1], f'perceptual-d{scored[0][0]}')
            still.remove(rel)

    rows.sort(key=lambda r: r['new'])
    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    json.dump(still, open(os.path.join(W, 'moves_unresolved5.json'), 'w'), indent=1)
    print(f'assigned {len(rows) - rows_before}, still open {len(still)}')
    print('methods:', Counter(r['how'] for r in rows).most_common())
    print('originals used twice:', len([o for o, c in Counter(r['orig'] for r in rows).items() if c > 1]))
    for s in still[:20]:
        print('  open:', s)


def dham(a, b):
    return bin(a ^ b).count('1')


if __name__ == "__main__":
    main()
