#!/usr/bin/env python3
"""Resolve the last open moves rows by content, not by metadata.


L9  hash-identical: PNG/HEIC/NEF/TIFF were never re-encoded, so the surviving file
    is byte-identical to its original.  Hash the survivor and the candidate originals.
L10 tie-is-harmless: where metadata ranking tied, check whether the tied originals
    are byte-identical to each other; if so the choice cannot be wrong.
L11 perceptual: for recompressed JPEGs still tied, compare a 16x16 dHash of the
    survivor against each tied original and keep a clear winner.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rebuild_moves4.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import io
import json
import os
import re
from collections import Counter, defaultdict

W = '/home/lario/photos-reorg-work'
BK = '/mnt/xfs/photos-originals-backup'
NEW = '/home/lario/Pictures/Photos.new'
OLD = '/home/lario/Pictures/Photos'
TS = re.compile(r'(?:^|_)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')
JPEGISH = {'jpg', 'jpeg', 'jpe'}
RAWS = {'nef', 'cr2', 'cr3', 'arw', 'raf', 'dng', 'orf', 'rw2'}
DATE_CHAIN = ['exif:datetimeoriginal', 'exififd:datetimeoriginal', 'ifd0:datetimeoriginal',
              'xmp:datetimecreated', 'xmp:datecreated', 'xmp:createdate', 'xmp:modifydate',
              'exif:createdate', 'exififd:createdate', 'ifd0:createdate', 'ifd0:datetime',
              'quicktime:createdate', 'quicktime:trackcreatedate', 'composite:datetimecreated',
              'file:filemodifydate', 'system:filemodifydate', 'file:filecreatedate']
import datetime as _dt
import hashlib

WORDS = re.compile(r'[a-z]{4,}')


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
    if not mm:
        return None
    return f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} {mm.group(4)}:{mm.group(5)}:{mm.group(6)}'


def digest(path):
    h = hashlib.blake2b()
    with open(path, 'rb') as fh:
        while True:
            b = fh.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


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
    open_rows = json.load(open(os.path.join(W, 'moves_unresolved3.json')))
    used = {r['orig'] for r in rows}
    recs = json.load(open(os.path.join(W, 'meta_backup_dates.json')))
    bak = {}
    for r in recs:
        src = r.get('SourceFile')
        if not src:
            continue
        rel = os.path.relpath(src, BK)
        m = norm(r)
        try:
            size = os.path.getsize(src)
        except OSError:
            size = 0
        bak[rel] = dict(date=(date_of(m) or '')[:10], ext=ext_of(rel, m), size=size,
                        junk=is_junk(os.path.basename(rel)))
    free = lambda rel: rel not in used and rel in bak and not bak[rel]['junk']

    lands = defaultdict(Counter)
    for r in rows:
        lands[os.path.dirname(r['orig'])][r['folder']] += 1
    by_date = defaultdict(list)
    for rel, v in bak.items():
        if v['date']:
            by_date[v['date']].append(rel)

    def candidates(rel):
        want = ts(rel)
        ext = ext_of(rel, {})
        d0 = _dt.date.fromisoformat(want[:10]) if want else None
        pool = []
        if d0:
            for delta in (0, -1, 1, -2, 2, -3, 3):
                for o in by_date.get((d0 + _dt.timedelta(days=delta)).isoformat(), []):
                    if free(o) and bak[o]['ext'] == ext:
                        pool.append(o)
        stem = re.sub(r'^\d+_', '', os.path.splitext(os.path.basename(rel))[0]).casefold()
        if not pool:
            pool = [o for o in bak if free(o) and bak[o]['ext'] == ext
                    and os.path.splitext(os.path.basename(o))[0].casefold() == stem]
        return sorted(set(pool))

    def assign(rel, orig, how):
        rows.append({'new': rel, 'orig': orig, 'orig_library': os.path.join(OLD, orig),
                     'backup': os.path.join(BK, orig), 'kind': kind_of(bak[orig]['ext']),
                     'change': 'unchanged', 'bytes_before': str(bak[orig]['size']),
                     'bytes_after': str(os.path.getsize(os.path.join(NEW, rel))),
                     'how': how, 'dt': ts(rel) or '', 'folder': os.path.dirname(rel)})
        used.add(orig)

    still, log = [], []
    # ---- L9 content hash of the survivor --------------------------------
    for rel in list(open_rows):
        p = os.path.join(NEW, rel)
        if not os.path.isfile(p):
            still.append(rel)
            open_rows.remove(rel)
            continue
        pool = candidates(rel)
        if not pool:
            still.append(rel)
            open_rows.remove(rel)
            continue
        nh = digest(p)
        hits = [o for o in pool if bak[o]['size'] == os.path.getsize(p) and digest(os.path.join(BK, o)) == nh]
        if hits:
            assign(rel, hits[0], 'hash-identical' if len(hits) == 1 else 'hash-identical-dup')
            log.append(('hash', rel, hits[0], len(hits)))
            open_rows.remove(rel)
        else:
            still.append(rel)
            open_rows.remove(rel)

    # ---- L10/L11 metadata ties: identical originals, then perceptual ----
    for rel in list(still):
        pool = candidates(rel)
        if not pool:
            continue
        scored = sorted(
            pool,
            key=lambda o: (100 * lands[os.path.dirname(o)].get(os.path.dirname(rel), 0)
                           + (10 if set(WORDS.findall(os.path.dirname(rel).lower()))
                               & set(os.path.dirname(o).lower().split()) else 0)),
            reverse=True)
        top = scored[0]
        top_score = 100 * lands[os.path.dirname(top)].get(os.path.dirname(rel), 0)
        tied = [o for o in pool if 100 * lands[os.path.dirname(o)].get(os.path.dirname(rel), 0) == top_score]
        if len(tied) > 1:
            dig = {o: digest(os.path.join(BK, o)) for o in tied}
            same = [o for o in tied if dig[o] == dig[top]]
            if len(same) == len(tied):
                assign(rel, top, 'tie-interchangeable')
                log.append(('tie-identical', rel, top, len(tied)))
                still.remove(rel)
                continue
            nh = dhash(os.path.join(NEW, rel))
            best, best_d = None, None
            for o in tied:
                try:
                    d = ham(nh, dhash(os.path.join(BK, o)))
                except Exception:
                    continue
                if best_d is None or d < best_d:
                    best, best_d = o, d
            if best is not None and best_d <= 12:
                assign(rel, best, f'perceptual-d{best_d}')
                log.append(('perceptual', rel, best, best_d))
                still.remove(rel)
                continue
        else:
            assign(rel, top, 'evidence-rank2')
            log.append(('rank2', rel, top, 1))
            still.remove(rel)

    rows.sort(key=lambda r: r['new'])
    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    json.dump(still, open(os.path.join(W, 'moves_unresolved4.json'), 'w'), indent=1)
    print('assigned this pass:', Counter(k for k, *_ in log).most_common())
    print('still open:', len(still))
    print('methods:', Counter(r['how'] for r in rows).most_common())
    dupes = [o for o, c in Counter(r['orig'] for r in rows).items() if c > 1]
    print('originals used twice:', len(dupes), dupes[:3])
    for s in still[:15]:
        print('  open:', s)


if __name__ == "__main__":
    main()
