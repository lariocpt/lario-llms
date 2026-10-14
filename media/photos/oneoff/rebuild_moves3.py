#!/usr/bin/env python3
"""Final pass over the open moves rows: rank candidates with folder-provenance evidence.


For each open row, candidates are the still-unused backup files with the same
extension whose extracted date matches the filename date (or is within a few days,
which covers files the pipeline dated from a source the backup copy no longer
carries).  Candidates are scored by

  dimensions equal                +1000
  folder already known to land     +100 * number of resolved files from that old
  in this new folder                folder that were placed in this new folder
  folder words present in the      +10
  new folder name
  output could have shrunk from    +50 (original >= output, ratio 0.08..1.0)
  exact date                       +200 (vs +40 within the window)

and assigned only when the winner is unambiguous (strictly ahead of the runner-up).
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rebuild_moves3.py
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

TS = re.compile(r'(?:^|_)(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})')
JPEGISH = {'jpg', 'jpeg', 'jpe'}
RAWS = {'nef', 'cr2', 'cr3', 'arw', 'raf', 'dng', 'orf', 'rw2'}
DATE_CHAIN = ['exif:datetimeoriginal', 'exififd:datetimeoriginal', 'ifd0:datetimeoriginal',
              'xmp:datetimecreated', 'xmp:datecreated', 'xmp:createdate', 'xmp:modifydate',
              'exif:createdate', 'exififd:createdate', 'ifd0:createdate', 'ifd0:datetime',
              'quicktime:createdate', 'quicktime:trackcreatedate', 'composite:datetimecreated',
              'file:filemodifydate', 'system:filemodifydate', 'file:filecreatedate']
WORDS = re.compile(r'[a-z][a-z]+')
import datetime as _dt


def norm(d):
    return {k.lower(): v for k, v in d.items()}


def date_of(m):
    for k in DATE_CHAIN:
        v = m.get(k)
        if v:
            s = str(v)[:19].replace('T', ' ')
            mm = re.match(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2}:\d{2})', s.replace(':', '-', 2))
            if mm:
                return f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} {mm.group(4)}'
    return None


def dims_of(m):
    s = str(m.get('composite:imagesize') or '')
    mm = re.match(r'(\d+)x(\d+)', s)
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
    if e in ('mp4', 'mov', 'avi', 'm4v', 'mpg', 'mpeg', '3gp', 'wmv', 'flv'):
        return 'video'
    return 'other'


def is_junk(name):
    return name.startswith('._') or name == '.DS_Store' or name.lower().endswith('.aae')


def day(s):
    try:
        return _dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'))))
    open_rows = json.load(open(os.path.join(W, 'moves_unresolved2.json')))
    used = {r['orig'] for r in rows}

    newm = {}
    for rel in open_rows:
        p = os.path.join(NEW, rel)
        newm[rel] = os.path.getsize(p) if os.path.isfile(p) else 0

    recs = json.load(open(os.path.join(W, 'meta_backup_dates.json')))
    bak = {}
    for r in recs:
        src = r.get('SourceFile')
        if not src:
            continue
        rel = os.path.relpath(src, BK)
        m = norm(r)
        name = os.path.basename(rel)
        try:
            size = os.path.getsize(src)
        except OSError:
            size = 0
        bak[rel] = dict(dt=date_of(m), date=(date_of(m) or '')[:10], dims=dims_of(m),
                        ext=ext_of(rel, m), size=size, junk=is_junk(name))
    free = lambda rel: rel not in used and rel in bak and not bak[rel]['junk']

    # provenance evidence: old folder -> new folder, from the rows already resolved
    lands = defaultdict(Counter)
    for r in rows:
        lands[os.path.dirname(r['orig'])][r['folder']] += 1

    by_date = defaultdict(list)
    by_ext = defaultdict(list)
    for rel, v in bak.items():
        if v['date']:
            by_date[v['date']].append(rel)
        by_ext[v['ext']].append(rel)

    def ts(rel):
        mm = TS.search(os.path.basename(rel))
        if not mm:
            return None
        return f'{mm.group(1)}-{mm.group(2)}-{mm.group(3)} {mm.group(4)}:{mm.group(5)}:{mm.group(6)}'

    # new-file dimensions from the staged tree
    nmeta = json.load(open(os.path.join(W, 'meta_new.json')))
    ndims = {rel: dims_of(norm(nmeta[rel])) for rel in open_rows if rel in nmeta}
    assigned, still = [], []
    for rel in open_rows:
        folder = os.path.dirname(rel)
        want = ts(rel)
        date = (want or '')[:10]
        ext = ext_of(rel, {})
        nsize = newm.get(rel, 0)
        nd = ndims.get(rel)
        pool = []
        if date:
            d0 = day(date)
            for delta in (0, -1, 1, -2, 2, -3, 3):
                dd = (d0 + _dt.timedelta(days=delta)).isoformat() if d0 else None
                for o in by_date.get(dd, []):
                    if free(o) and bak[o]['ext'] == ext:
                        pool.append((o, 200 if delta == 0 else 40))
                if len({o for o, _ in pool}) >= 1 and delta == 0:
                    break
        if not pool and os.path.basename(rel).lower().endswith('.zip'):
            continue
        best, second = None, None
        seen = set()
        for o, dscore in pool:
            if o in seen:
                continue
            seen.add(o)
            s = dscore
            v = bak[o]
            if nd and v['dims'] and v['dims'] == nd:
                s += 1000
            s += 100 * lands[os.path.dirname(o)].get(folder, 0)
            words = set(WORDS.findall(folder.lower()))
            ofolder = os.path.dirname(o).lower()
            if words & set(WORDS.findall(ofolder)):
                s += 10
            if nsize and v['size'] >= nsize and v['size'] < nsize * 12.5:
                s += 50
            if best is None or s > best[1]:
                best, second = (o, s), best
            elif second is None or s > second[1]:
                second = (o, s)
        if not best:
            still.append(rel)
            continue
        if second and second[1] >= best[1]:
            still.append(rel)
            continue
        orig = best[0]
        rows.append({'new': rel, 'orig': orig, 'orig_library': os.path.join(OLD, orig),
                     'backup': os.path.join(BK, orig), 'kind': kind_of(bak[orig]['ext']),
                     'change': 'recompressed' if nsize and bak[orig]['size'] > nsize * 1.05
                     else 'unchanged',
                     'bytes_before': str(bak[orig]['size']), 'bytes_after': str(nsize),
                     'how': 'evidence-rank', 'dt': want or '', 'folder': folder})
        used.add(orig)
        assigned.append((rel, orig, best[1], second[1] if second else None))

    rows.sort(key=lambda r: r['new'])
    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    json.dump(still, open(os.path.join(W, 'moves_unresolved3.json'), 'w'), indent=1)
    print(f'assigned {len(assigned)}, still open {len(still)}')
    print('methods:', Counter(r['how'] for r in rows).most_common())
    dupes = [o for o, c in Counter(r['orig'] for r in rows).items() if c > 1]
    print('originals used twice:', len(dupes))
    for rel, orig, sc, sc2 in assigned[:10]:
        print(f'  {rel}  <=  {orig}  (score {sc} vs {sc2})')
    print('open sample:', still[:8])


if __name__ == "__main__":
    main()
