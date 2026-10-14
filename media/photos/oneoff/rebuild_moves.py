#!/usr/bin/env python3
"""Rebuild the moves manifest: every file in Photos.new -> its original path.


plan.json and moves.csv were lost with /tmp, so the mapping is reconstructed
from what is on disk, in this order of preference:

 1. folder   - foldermap.json says which old folder became this new folder, so
               candidates are limited to that one folder
 2. date     - the NNN_YYYYMMDD-HHMMSS name is the date the pipeline extracted;
               compare it with the date extracted the same way from the original
 3. pixels   - identical dimensions (compression never resizes)
 4. stem     - undated files kept their original filename after the NNN_ prefix
 5. size     - a recompressed JPEG must be smaller than its original

Each new file must end with exactly one candidate; anything else is reported.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rebuild_moves.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import re
from collections import Counter, defaultdict

NEW = '/home/lario/Pictures/Photos.new'
OLD = '/home/lario/Pictures/Photos'
BK = '/mnt/xfs/photos-originals-backup'
WORK = '/home/lario/photos-reorg-work'
IMG = ('.jpg', '.jpeg', '.heic', '.heif', '.png', '.gif', '.tif', '.tiff',
       '.nef', '.dng', '.cr2', '.arw', '.bmp')
VID = ('.mp4', '.mov', '.m4v', '.avi', '.3gp', '.mpg', '.mpeg', '.wmv')

DATE_SRC = ['exif:datetimeoriginal', 'exif:datetimedigitized',
            'exif:offsettimeoriginal', 'quicktime:createdate',
            'track1:mediacreatedate', 'file:filemodifydate']


def load(path):
    return {k: {str(kk).lower(): vv for kk, vv in v.items()}
            for k, v in json.load(open(path)).items()}


def getd(rec):
    for t in DATE_SRC:
        v = rec.get(t)
        if isinstance(v, list):
            v = v[0]
        if v:
            s = str(v).replace('T', ' ')[:19]
            m = re.match(r'(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})', s)
            if m:
                s = '-'.join(m.groups()[:3]) + ' ' + ':'.join(m.groups()[3:])
                if s > '2000-01-01':
                    return s
    return None


def dims(rec):
    sz = rec.get('composite:imagesize')
    if isinstance(sz, list):
        sz = sz[0]
    if isinstance(sz, str):
        m = re.match(r'(\d+)x(\d+)', sz)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def is_junk(rel):
    b = os.path.basename(rel)
    return (b.startswith('._') or b.lower() in ('.ds_store', 'thumbs.db', 'desktop.ini')
            or rel.lower().endswith('.aae'))


def main():
    nw = load(f'{WORK}/meta_new.json')
    bk = load(f'{WORK}/meta_backup.json')
    vd = load(f'{WORK}/meta_videos.json')
    foldermap = json.load(open(f'{WORK}/foldermap.json'))
    videomap = json.load(open(f'{WORK}/videomap.json'))

    # inverse: new folder -> the old folders that could have produced it
    inv = defaultdict(list)
    for o, n in foldermap.items():
        inv[n].append(o)
    old_by_dir = defaultdict(list)
    for rel in bk:
        old_by_dir[os.path.dirname(rel)].append(rel)

    # candidate index over backup images by (date, dims). Candidacy is decided
    # by what exiftool says the file IS, not by its extension: some originals
    # are JPEGs with no extension at all.
    def is_image(rec):
        mime = rec.get('file:mimetype') or rec.get('File:MIMEType') or ''
        return mime.startswith('image/')

    by_date_dims = defaultdict(list)
    by_date = defaultdict(list)
    for rel, rec in bk.items():
        if is_junk(rel) or not is_image(rec):
            continue
        dt = getd(rec)
        if not dt:
            continue
        key = (dt[:10].replace('-', '') + '-' + dt[11:].replace(':', ''))
        by_date[key].append(rel)
        by_date_dims[(key, dims(rec))].append(rel)

    used = set()
    rows = []
    amb = []
    for rel in sorted(nw):
        rec = nw[rel]
        base = os.path.basename(rel)
        d = os.path.dirname(rel)
        ext = os.path.splitext(base)[1].lower()
        m = re.match(r'^(\d{3})_(.*)(\.[A-Za-z0-9]+)$', base)
        stem, seq = (m.group(2), m.group(1)) if m else ('', '')
        why = ''
        pool = None
        cands = []
        if d.startswith('Undated'):
            # undated: original filename preserved after the sequence prefix
            old_dirs = inv.get(d) or [x.split('/', 1)[1].replace(' (clock never set)', '')
                                      for x in [d]]
            for od in old_dirs:
                for cand in old_by_dir.get(od, []):
                    if os.path.splitext(os.path.basename(cand))[0] == stem:
                        cands.append(cand)
            why = 'undated-stem'
        if not cands:
            pool = None
            for od in inv.get(d, []):
                pool = old_by_dir.get(od, [])
                if pool:
                    break
            key = stem if re.match(r'\d{8}-\d{6}$', stem) else None
            if key:
                cd = [c for c in by_date_dims.get((key, dims(rec)), [])]
                cands = cd or list(by_date.get(key, []))
                why = 'folder+date+dims' if cd else 'date+dims'
                if pool is not None and len(cands) > 1:
                    narrowed = [c for c in cands if c in pool]
                    if narrowed:
                        cands = narrowed
                        why = 'folder+date'
        if len(cands) > 1 and pool:
            n2 = [c for c in cands if c in pool]
            if n2:
                cands = n2
        if len(cands) > 1:
            # smallest-size-plausible original wins (recompressed is smaller)
            myn = os.path.getsize(os.path.join(NEW, rel))
            ok = [c for c in cands
                  if os.path.getsize(os.path.join(BK, c)) >= myn * 0.6]
            if len(ok) == 1:
                cands = ok
                why = '+size'
        if len(cands) == 1:
            o = cands[0]
            used.add(o)
            ob = os.path.getsize(os.path.join(BK, o))
            nb = os.path.getsize(os.path.join(NEW, rel))
            kind = ('raw' if ext in ('.nef', '.dng', '.cr2', '.arw') else
                    'video' if ext in VID else 'image')
            what = ('recompressed' if ext in ('.jpg', '.jpeg') and nb < ob
                    else 'unchanged')
            rows.append({'new': rel, 'orig': o,
                         'orig_library': os.path.join(OLD, o),
                         'backup': os.path.join(BK, o), 'kind': kind,
                         'change': what, 'bytes_before': ob,
                         'bytes_after': nb, 'how': why,
                         'dt': getd(rec) or '', 'folder': d})
        else:
            amb.append((rel, len(cands), cands))

    # ---- is the NNN sequence the original filename order? Measure it on the
    # rows that were resolved without guessing, then reuse the rule.
    seq_ok = seq_bad = 0
    per_folder = defaultdict(list)
    for r in rows:
        m = re.match(r'^(\d{3})_', os.path.basename(r['new']))
        per_folder[(r['folder'], r['dt'])].append((int(m.group(1)), r['orig']))
    for key, items in per_folder.items():
        if len(items) < 2:
            continue
        names = [o for _, o in sorted(items)]
        if names == sorted(names):
            seq_ok += 1
        else:
            seq_bad += 1
    print(f'sequence-order rule, measured on {seq_ok + seq_bad} multi-file '
          f'groups: {seq_ok} follow sorted original names, {seq_bad} do not')

    def emit(rel, orig, why):
        ob = os.path.getsize(os.path.join(BK, orig))
        nb = os.path.getsize(os.path.join(NEW, rel))
        ext = os.path.splitext(rel)[1].lower()
        kind = ('raw' if ext in ('.nef', '.dng', '.cr2', '.arw') else
                'video' if ext in VID else 'image')
        rows.append({'new': rel, 'orig': orig,
                     'orig_library': os.path.join(OLD, orig),
                     'backup': os.path.join(BK, orig), 'kind': kind,
                     'change': ('recompressed'
                                if ext in ('.jpg', '.jpeg') and nb < ob
                                else 'unchanged'),
                     'bytes_before': ob, 'bytes_after': nb, 'how': why,
                     'dt': getd(nw[rel]) or '', 'folder': os.path.dirname(rel)})
        used.add(orig)

    # ---- second pass: same folder, same instant, several files -> the
    # sequence numbering decides, exactly as measured above.
    groups = defaultdict(list)
    for rel, n, cands in amb:
        if not cands:
            continue
        m = re.match(r'^(\d{3})_', os.path.basename(rel))
        if not m:
            continue
        groups[(os.path.dirname(rel), os.path.basename(rel)[4:19])].append(
            (int(m.group(1)), rel, tuple(cands)))
    still = []
    for key, items in sorted(groups.items()):
        items.sort()
        pool = sorted({c for _, _, cs in items for c in cs if c not in used})
        same = all(len(items[i][2]) == len(items[0][2]) for i in range(len(items)))
        if same and len(pool) == len(items):
            for (seq, rel, cs), orig in zip(items, pool):
                emit(rel, orig, 'date+order')
        else:
            still.extend((rel, len(cs), list(cs)) for _, rel, cs in items)
    amb2 = [(rel, n, c) for rel, n, c in amb if not c] + still

    print(f'new files: {len(nw)}   matched: {len(rows)}   unresolved: {len(amb2)}')
    print(Counter(r['how'] for r in rows).most_common())
    print(Counter((r['kind'], r['change']) for r in rows).most_common())
    for rel, n, c in amb2[:15]:
        print(f'  UNRESOLVED {n:2d}  {rel}   e.g. {c}')
    # 1:1 sanity
    oc = Counter(r['orig'] for r in rows)
    print('originals used twice:', sum(1 for v in oc.values() if v > 1))
    bb = sum(r['bytes_before'] for r in rows)
    ba = sum(r['bytes_after'] for r in rows)
    print(f'matched bytes: {bb/2**30:.2f} -> {ba/2**30:.2f} GB')
    with open(f'{WORK}/manifest-moves.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    json.dump(amb2, open(f'{WORK}/moves_unresolved.json', 'w'), indent=1)
    print('wrote manifest-moves.csv')


if __name__ == "__main__":
    main()
