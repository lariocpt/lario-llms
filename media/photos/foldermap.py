#!/usr/bin/env python3
"""Rebuild, without the lost plan.json: which new photo folder came from which

old folder, and where each of the 364 remaining videos belongs.

Evidence used, not guesswork: a new filename NNN_YYYYMMDD-HHMMSS.ext records
the date the pipeline extracted, so a backup file whose own extracted date and
pixel dimensions land on exactly one such name is a match. Voting over the
matched files of an old folder gives that folder's destination in the new tree.
Videos then inherit their old folder's destination; their own timestamp gives
the filename, numbered in time order inside the folder like the photos are.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/foldermap.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import re
from collections import Counter, defaultdict

from paths import LIB as OLD
from paths import STAGING as NEW
WORK = '/home/lario/photos-reorg-work'

DATE_SRC = ['exif:datetimeoriginal', 'exif:datetimedigitized',
            'exif:offsettimeoriginal', 'quicktime:createdate',
            'track1:mediacreatedate', 'file:filemodifydate']
JUNK = re.compile(r'(^|/)(\._|\.DS_Store$|Thumbs\.db$)', re.I)


def load(path):
    """exiftool group prefixes vary by case (EXIF: vs ExifIFD:), so key them
    lower-cased and look tags up by name only."""
    return {k: {str(kk).lower(): vv for kk, vv in v.items()}
            for k, v in json.load(open(path)).items()}


def is_junk(rel):
    b = os.path.basename(rel)
    return (b.startswith('._') or b in ('.DS_Store', 'Thumbs.db', 'desktop.ini')
            or rel.lower().endswith('.aae'))


def getd(rec):
    """Date + whether it came from real capture metadata."""
    for t in DATE_SRC:
        v = rec.get(t)
        if isinstance(v, list):
            v = v[0]
        if v:
            v = str(v).replace('T', ' ')[:19].replace('T', ' ')
            m = re.match(r'(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})', v)
            if m:
                s = '-'.join(m.groups()[:3]) + ' ' + ':'.join(m.groups()[3:])
                if s > '2000-01-01':
                    return s, t != 'file:filemodifydate'
    return None, False


def dims(rec):
    sz = rec.get('composite:imagesize')
    if isinstance(sz, list):
        sz = sz[0]
    if isinstance(sz, str):
        m = re.match(r'(\d+)x(\d+)', sz)
        if m:
            return int(m.group(1)), int(m.group(2))
    w, h = rec.get('file:imagewidth'), rec.get('file:imageheight')
    if w and h:
        return int(str(w).split()[0]), int(str(h).split()[0])
    w, h = rec.get('quicktime:movieheaderwidth'), rec.get('quicktime:movieheaderheight')
    if w and h:
        return int(str(w).split()[0]), int(str(h).split()[0])
    return None


def main():
    bk = load(f'{WORK}/meta_backup.json')
    nw = load(f'{WORK}/meta_new.json')

    # index new tree by the timestamp its filename carries
    new_by_ts = defaultdict(list)
    undated_dirs = set()
    for rel, rec in nw.items():
        base = os.path.basename(rel)
        m = re.match(r'\d{3}_(\d{8})-(\d{6})\.', base)
        if m:
            new_by_ts[(m.group(1), m.group(2))].append((rel, dims(rec)))
        top = rel.split('/')[0]
        if top == 'Undated':
            undated_dirs.add('/'.join(rel.split('/')[:2]))

    # match backup files to new files
    votes = defaultdict(Counter)
    matched = {}
    for rel, rec in bk.items():
        if is_junk(rel):
            continue
        ext = os.path.splitext(rel)[1].lower()
        if ext in ('.mp4', '.mov', '.m4v', '.avi', '.3gp', '.mpg', '.mpeg', '.wmv'):
            continue
        dt, real = getd(rec)
        if not dt:
            continue
        key = (dt[:10].replace('-', ''), dt[11:].replace(':', ''))
        cands = new_by_ts.get(key) or []
        d = dims(rec)
        if len(cands) > 1 and d:
            cands = [c for c in cands if c[1] == d] or cands
        if len(cands) == 1:
            new_rel = cands[0][0]
            matched[rel] = new_rel
            votes[os.path.dirname(rel)][os.path.dirname(new_rel)] += 1
        elif len(cands) > 1:
            votes[os.path.dirname(rel)][os.path.dirname(cands[0][0])] += 0.5

    foldermap = {}
    ambig = []
    for fold, c in votes.items():
        if not c or not c.most_common(1)[0][1]:
            continue
        best, n = c.most_common(1)[0]
        tot = sum(v for _, v in c.items()) or 1
        if n / tot >= 0.5:
            foldermap[fold] = best
        else:
            ambig.append((fold, c.most_common(3)))

    # undated folders: "Undated/<old folder name> (clock never set)". This is
    # authoritative - those folders were excluded from dating on purpose, so a
    # stray vote landing on a same-named date folder must not win.
    for u in sorted(undated_dirs):
        name = u.split('/', 1)[1].replace(' (clock never set)', '')
        if foldermap.get(name) and foldermap[name] != u:
            print(f'  override {name!r}: {foldermap[name]!r} -> {u!r}')
        foldermap[name] = u

    print(f'folders with votes: {len(votes)}  mapped: {len(foldermap)}  '
          f'ambiguous: {len(ambig)}')
    for fold, top in ambig[:8]:
        print('  AMBIG', repr(fold), top)
    print(f'sample mappings:')
    for k in list(sorted(foldermap))[:6]:
        print(f'  {k!r} -> {foldermap[k]!r}')

    # ---- videos
    vd = load(f'{WORK}/meta_videos.json')
    print(f'backup files matched to a new file: {len(matched)} '
          f'of {len(nw)} new files')
    by_folder = defaultdict(list)
    for rel in vd:
        by_folder[os.path.dirname(rel)].append(rel)
    plan = {}
    missing = []

    def fallback_dir(fold, dt):
        """Folders the photo vote could not place (video-only folders). Same
        convention the photo tree uses: YYYY/YYYY-MM-DD <name minus year>,
        loose top-level files to Unsorted day folders."""
        if fold == '':
            return (f'{dt[:4]}/{dt[:10]} Unsorted' if dt else 'Undated/Unsorted')
        event = re.sub(r',?\s*\d{4}$', '', fold).strip() or fold
        if dt:
            return f'{dt[:4]}/{dt[:10]} {event}'
        return f'Undated/{event}'

    for fold, files in by_folder.items():
        dest = foldermap.get(fold)
        if dest is None:
            missing.append((fold, len(files)))
        for rel in files:
            rec = vd[rel]
            dt, real = getd(rec)
            dest_dir = dest or fallback_dir(fold, dt)
            if dest_dir.startswith('Undated'):
                name = os.path.splitext(os.path.basename(rel))[0]
            else:
                name = dt[:10].replace('-', '') + '-' + dt[11:].replace(':', '')
            plan[rel] = {'dest_dir': dest_dir, 'stamp': name,
                         'dt': dt, 'real': real, 'dims': dims(rec),
                         'size': os.path.getsize(os.path.join(OLD, rel))}
    print(f'\nvideo folders: {len(by_folder)}  unmapped (fallback Unsorted/Undated): '
          f'{len(missing)}')
    for fold, n in missing[:10]:
        print('  UNMAPPED', repr(fold), n, 'files')
    # order and number inside each destination folder
    out = {}
    groups = defaultdict(list)
    for rel, e in plan.items():
        groups[e['dest_dir']].append((e['stamp'], rel))
    for d, items in groups.items():
        for i, (stamp, rel) in enumerate(sorted(items), 1):
            ext = os.path.splitext(rel)[1].lower()
            base = f'{i:03d}_{stamp}{ext}'
            e = dict(plan[rel])
            e['dest_name'] = base
            e['dest'] = f'{d}/{base}'
            out[rel] = e
    # collision check
    dests = Counter(e['dest'] for e in out.values())
    print('destination collisions:', sum(1 for v in dests.values() if v > 1))
    print('video destinations under', len({e['dest_dir'] for e in out.values()}),
          'folders')
    for rel in list(sorted(out))[:5]:
        print(f'  {rel[:58]!r:62} -> {out[rel]["dest"]}')
    json.dump(out, open(f'{WORK}/videomap.json', 'w'), indent=1)
    json.dump(foldermap, open(f'{WORK}/foldermap.json', 'w'), indent=1)
    print('wrote videomap.json, foldermap.json')


if __name__ == "__main__":
    main()
