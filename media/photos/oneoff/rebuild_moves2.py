#!/usr/bin/env python3
"""Resolve the last unresolved moves rows and finalise manifest-moves.csv.


The already-resolved rows (7,458) are kept untouched. The remainder is matched with
a layered, deterministic strategy; every assignment records how it was decided:

  folder+date+dims2  candidate in the mapped old folder, same filename date and size
  folder+date2       same, unique without dimensions
  date+dims          unique unused file anywhere with that date and dimensions
  undated-stem2      Undated/<NNN>_<original name>: stem match inside the mapped folder
  undated-order      Undated group: NNN order == sorted original filename order
  order-zip          same folder+date group: NNN order == sorted original name order
  size-plausible     single candidate that could have produced this smaller output

Extensions are compared loosely (the pipeline normalised .jpeg -> .jpg when it
recompressed).  Nothing is guessed where two originals are truly interchangeable:
those rows stay in moves_unresolved2.json.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rebuild_moves2.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

W = '/home/lario/photos-reorg-work'
BK = '/mnt/xfs/photos-originals-backup'
NEW = '/home/lario/Pictures/Photos.new'
OLD = '/home/lario/Pictures/Photos'

TS = re.compile(r'(?:^|_)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')
STEM_PREFIX = re.compile(r'^\d+_(.*)$')
JPEGISH = {'jpg', 'jpeg', 'jpe'}
RAWS = {'nef', 'cr2', 'cr3', 'arw', 'raf', 'dng', 'orf', 'rw2'}

DATE_CHAIN = ['exif:datetimeoriginal', 'exififd:datetimeoriginal', 'ifd0:datetimeoriginal',
              'xmp:datetimecreated', 'xmp:datecreated', 'xmp:createdate', 'xmp:modifydate',
              'exif:createdate', 'exififd:createdate', 'ifd0:createdate', 'ifd0:datetime',
              'quicktime:createdate', 'quicktime:trackcreatedate', 'matroska:dateutc',
              'composite:datetimecreated', 'file:filemodifydate', 'system:filemodifydate',
              'file:filecreatedate']


def norm(d):
    return {k.lower(): v for k, v in d.items()}


def date_of(m):
    for k in DATE_CHAIN:
        v = m.get(k)
        if v:
            s = str(v)[:19].replace('T', ' ').replace(':', '-', 2)
            m2 = re.match(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})', s)
            if m2:
                return f'{m2.group(1)} {m2.group(2)}'
    return None


def dims_of(m):
    s = m.get('composite:imagesize') or ''
    mm = re.match(r'(\d+)x(\d+)', str(s))
    if mm:
        return int(mm.group(1)), int(mm.group(2))
    w, h = m.get('file:imagewidth'), m.get('file:imageheight')
    if w and h:
        return int(w), int(h)
    return None


def ext_of(path, m):
    e = (m.get('file:filetypeextension') or os.path.splitext(path)[1][1:]).lower()
    return 'jpg' if e in JPEGISH else e


def kind_of(e):
    if e in RAWS:
        return 'raw'
    if e in ('jpg', 'png', 'heic', 'gif', 'tif', 'tiff', 'bmp', 'webp'):
        return 'image'
    if e in ('mp4', 'mov', 'avi', 'm4v', 'mpg', 'mpeg', '3gp', 'wmv', 'flv'):
        return 'video'
    return 'other'


def is_junk(name):
    return (name.startswith('._') or name == '.DS_Store' or name.lower().endswith('.aae'))


def load_dates():
    recs = json.load(open(os.path.join(W, 'meta_backup_dates.json')))
    out = {}
    for r in recs:
        src = r.get('SourceFile')
        if not src:
            continue
        rel = os.path.relpath(src, BK)
        m = norm(r)
        out[rel] = dict(path=rel, abs=src, dt=date_of(m), dims=dims_of(m),
                        ext=ext_of(rel, m), date=(date_of(m) or '')[:10],
                        junk=is_junk(os.path.basename(rel)))
    return out


def load_new():
    d = json.load(open(os.path.join(W, 'meta_new.json')))
    out = {}
    for rel, v in d.items():
        m = norm(v)
        out[rel] = dict(dims=dims_of(m), ext=ext_of(rel, m),
                        size=os.path.getsize(os.path.join(NEW, rel))
                        if os.path.isfile(os.path.join(NEW, rel)) else 0,
                        dt=date_of(m))
    return out


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    unresolved = [e[0] if isinstance(e, list) else e['path']
                  for e in json.load(open(os.path.join(W, 'moves_unresolved.json')))]
    used = {r['orig'] for r in rows}
    print(f'start: {len(rows)} resolved, {len(unresolved)} to go, {len(used)} originals used')

    bak = load_dates()
    newm = load_new()
    for v in bak.values():
        try:
            v['size'] = os.path.getsize(v['abs'])
        except OSError:
            v['size'] = 0
    print(f'backup dated index: {sum(1 for v in bak.values() if v["dt"])} of {len(bak)}')

    fmap = json.load(open(os.path.join(W, 'foldermap.json')))
    inv = defaultdict(set)
    for oldfolder, newfolder in fmap.items():
        inv[newfolder].add(oldfolder)

    # ---- candidate pools -------------------------------------------------
    free = lambda rel: rel not in used and rel in bak and not bak[rel]['junk']
    by_folder_date = defaultdict(list)
    by_date_dims = defaultdict(list)
    by_folder_stem = defaultdict(list)
    by_stem = defaultdict(list)
    for rel, v in bak.items():
        f = os.path.dirname(rel)
        if v['date']:
            by_folder_date[(f, v['date'])].append(rel)
            by_date_dims[(v['date'], v['dims'], v['ext'])].append(rel)
        stem = os.path.splitext(os.path.basename(rel))[0].casefold()
        by_folder_stem[(f, stem)].append(rel)
        by_stem[stem].append(rel)

    def folders_for(newfolder):
        s = set(inv.get(newfolder, set()))
        if newfolder.endswith('Unsorted'):
            s.add('')                      # loose files at the old library root
        return s

    def row_ts(rel):
        mm = TS.search(os.path.basename(rel))
        if not mm:
            return None, None
        return (f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)}',
                f'{mm.group(4)}:{mm.group(5)}:{mm.group(6)}')

    pending = list(dict.fromkeys(unresolved))
    reasons = {}

    def take(newrel, origrel, how):
        rows.append({'new': newrel, 'orig': origrel,
                     'orig_library': os.path.join(OLD, origrel),
                     'backup': os.path.join(BK, origrel),
                     'kind': kind_of(bak[origrel]['ext']),
                     'change': 'unchanged',
                     'bytes_before': str(bak[origrel]['size']),
                     'bytes_after': str(newm.get(newrel, {}).get('size', 0)),
                     'how': how,
                     'dt': newm.get(newrel, {}).get('dt') or '',
                     'folder': os.path.dirname(newrel)})
        used.add(origrel)
        reasons[newrel] = how
        pending.remove(newrel)

    # L1/L2: folder + filename date, dimensions first
    for _ in range(3):
        progressed = 0
        for newrel in list(pending):
            folder = os.path.dirname(newrel)
            date, _t = row_ts(newrel)
            if not date:
                continue
            ext = newm.get(newrel, {}).get('ext') or ext_of(newrel, {})
            nd = newm.get(newrel, {}).get('dims')
            pool = [o for f in folders_for(folder) for o in by_folder_date.get((f, date), [])
                    if free(o) and bak[o]['ext'] == ext]
            if not pool:
                continue
            exact = [o for o in pool if bak[o]['dims'] == nd and nd]
            if len(exact) == 1:
                take(newrel, exact[0], 'folder+date+dims2')
                progressed += 1
            elif len(pool) == 1:
                take(newrel, pool[0], 'folder+date2')
                progressed += 1
        if not progressed:
            break

    # L3: unique file anywhere with that date, dimensions and extension
    for newrel in list(pending):
        date, _t = row_ts(newrel)
        if not date:
            continue
        nd = newm.get(newrel, {}).get('dims')
        ext = newm.get(newrel, {}).get('ext') or ext_of(newrel, {})
        pool = [o for o in by_date_dims.get((date, nd, ext), []) if free(o)]
        if len(pool) == 1:
            take(newrel, pool[0], 'date+dims')

    # L4: Undated rows carry the original filename after the NNN_ prefix
    for newrel in list(pending):
        base = os.path.basename(newrel)
        mm = STEM_PREFIX.match(os.path.splitext(base)[0])
        stem = (mm.group(1) if mm else os.path.splitext(base)[0]).casefold()
        folder = os.path.dirname(newrel)
        ext = newm.get(newrel, {}).get('ext') or ext_of(newrel, {})
        nd = newm.get(newrel, {}).get('dims')
        pool = [o for f in folders_for(folder)
                for o in by_folder_stem.get((f, stem), []) if free(o)]
        if not pool and folder.startswith('Undated/'):
            sub = re.sub(r' \((clock never set|undated)\)$', '', folder.split('/', 1)[1])
            for f in folders_for(folder) | {sub}:
                pool += [o for o in by_folder_stem.get((f, stem), []) if free(o)]
        if not pool:
            pool = [o for o in by_stem.get(stem, []) if free(o)]
        if not pool:
            continue
        exact = [o for o in pool if nd and bak[o]['dims'] == nd]
        exact = [o for o in (exact or pool) if bak[o]['ext'] == ext] or exact or pool
        if len(exact) == 1:
            take(newrel, exact[0], 'undated-stem2')
        elif len(set(os.path.basename(o) for o in pool)) == 1:
            take(newrel, pool[0], 'undated-stem-same-name')

    # L5: NNN order == sorted original filename order inside a folder/date group
    groups = defaultdict(list)
    for newrel in pending:
        date, _t = row_ts(newrel)
        groups[(os.path.dirname(newrel), date)].append(newrel)
    for (folder, date), items in sorted(groups.items()):
        if not date:
            continue
        ext = newm.get(items[0], {}).get('ext') or 'jpg'
        pool = sorted({o for f in folders_for(folder)
                       for o in by_folder_date.get((f, date), [])
                       if free(o) and bak[o]['ext'] == ext})
        items = sorted(items)
        if len(pool) == len(items) and pool:
            for newrel, origrel in zip(items, pool):
                if newrel in pending and free(origrel):
                    take(newrel, origrel, 'order-zip')

    # L5b: Undated groups ordered the same way
    ugroups = defaultdict(list)
    for newrel in pending:
        if not newrel.startswith('Undated/'):
            continue
        base = os.path.splitext(os.path.basename(newrel))[0]
        mm = STEM_PREFIX.match(base)
        stem = (mm.group(1) if mm else base).casefold()
        ugroups[(os.path.dirname(newrel), stem)].append(newrel)
    for (folder, stem), items in sorted(ugroups.items()):
        pool = sorted({o for f in folders_for(folder) | {re.sub(r' \((clock never set|undated)\)$', '',
                                                                folder.split('/', 1)[1])}
                       for o in by_folder_stem.get((f, stem), []) if free(o)})
        items = sorted(items, key=lambda p: (int(STEM_PREFIX.match(os.path.splitext(os.path.basename(p))[0]).group(1))
                                             if STEM_PREFIX.match(os.path.splitext(os.path.basename(p))[0]) else 0))
        if len(pool) == len(items) and pool:
            for newrel, origrel in zip(items, pool):
                if newrel in pending and free(origrel):
                    take(newrel, origrel, 'undated-order')

    # L6: one remaining candidate that could have shrunk to this size
    for newrel in list(pending):
        date, _t = row_ts(newrel)
        folder = os.path.dirname(newrel)
        ext = newm.get(newrel, {}).get('ext') or ext_of(newrel, {})
        nsize = newm.get(newrel, {}).get('size', 0)
        nd = newm.get(newrel, {}).get('dims')
        pool = [o for f in folders_for(folder) for o in by_folder_date.get((f, date), [])
                if free(o) and bak[o]['ext'] == ext and bak[o]['size'] >= nsize
                and (not nd or bak[o]['dims'] == nd)]
        if len(pool) == 1:
            take(newrel, pool[0], 'size-plausible')

    # L7: the two deliberate non-photo moves
    for newrel, origrel in [('Misc/Paris.zip', 'Paris/Paris.zip'),
                            ('_apps/photos/Photo Booth Library/Contents/PkgInfo',
                             'photos/Photo Booth Library/Contents/PkgInfo')]:
        if newrel in pending and origrel in bak and free(origrel):
            take(newrel, origrel, 'explicit-override')

    # change column: recompressed only where the surviving file is really smaller
    for r in rows:
        if not r['change'] or r['change'] == 'unchanged':
            try:
                if int(r['bytes_after']) and int(r['bytes_before']) < int(r['bytes_after']) * 0.95:
                    r['change'] = 'recompressed'
                else:
                    r['change'] = 'unchanged'
            except (TypeError, ValueError):
                pass

    rows.sort(key=lambda r: r['new'])
    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    json.dump(pending, open(os.path.join(W, 'moves_unresolved2.json'), 'w'), indent=1)

    print(f'\nresolved now: {len(rows)} rows, still open {len(pending)}')
    print('methods:', Counter(r['how'] for r in rows).most_common())
    dupes = [o for o, c in Counter(r['orig'] for r in rows).items() if c > 1]
    print('originals used twice:', len(dupes), dupes[:5])
    print('reasons this pass:', Counter(reasons.values()).most_common())
    if pending:
        print('still open, folder tally:',
              Counter(os.path.dirname(p) for p in pending).most_common(8))
        print('still open, extension tally:',
              Counter(os.path.splitext(p)[1] for p in pending).most_common(6))


if __name__ == "__main__":
    main()
