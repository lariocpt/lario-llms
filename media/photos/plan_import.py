#!/usr/bin/env python3
"""Plan (and optionally apply) the import of the two hhd source trees.


Rules, unchanged from the 2026-10-10 reorganisation:
  target  YYYY/YYYY-MM-DD <Event>/NNN_YYYYMMDD-HHMMSS.ext
  a day that already exists in the library keeps its existing folder (busiest
  one when a day has two); a new day gets the source folder's event name, or no
  name at all when the source folder says nothing ("Canon Unsorted", flat export)
  undated files -> Undated/<source folder>
  photos -> ~/Pictures/Photos,  videos -> /mnt/xfs/videos/videos (same shape)
  Grant Backup is archived intact, never imported (owner's decision)

usage: plan_import.py            dry run, prints the plan, writes import-plan.json
       APPLY=1 plan_import.py    moves the images (videos are a separate script)
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/plan_import.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")

# Parse arguments before anything else. This file computes the plan at module
# level, so a stray `--help` used to run the whole pass -- and, because the
# source trees of a finished import are drained, produce an *empty* plan and
# write it over the hand-edited one. Parsing first makes --help exit here.
import argparse as _argparse
_parser = _argparse.ArgumentParser(
    description="Plan the external-drive -> library import and write the plan file.")
_parser.add_argument("--dry", action="store_true",
                     help="print the plan, never write the plan file")
_args, _unused_args = _parser.parse_known_args()
PLAN_DRY = _args.dry
import csv
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict

W = '/home/lario/photos-reorg-work'
from paths import LIB
from paths import VIDLIB
from paths import HHD
ROOTS = {'Mac Photos': f'{HHD}/Mac Photos', 'Photosusa': f'{HHD}/Photosusa'}
ZIP_PROV = {}
if os.environ.get('ZIP_ROOTS') == '1':
    # staged archive contents. The tree tag is the archive name, so a candidate's
    # provenance can point back at the archive and at the path inside it.
    _z = json.load(open(f'{W}/zip-roots.json'))
    ROOTS.update(_z['roots'])
    ZIP_PROV = _z['prov']
    # staged path -> the exact thing it came out of, "Archive.zip::Elisa/x.jpg"
    PROV = {}
    for _l in open(f'{W}/zip-provenance.jsonl'):
        _d = json.loads(_l)
        PROV[_d['staged']] = _d['provenance']
else:
    PROV = {}
BUCKETS = os.environ.get('BUCKETS', 'new-candidates.json')
META = os.environ.get('META', 'meta_cand.jsonl')
PLAN = os.environ.get('PLAN', 'import-plan.json')
MANIFEST = os.environ.get('MANIFEST', 'manifest-imports.csv')
GRANT = 'photos/Grant Backup'
IMG = ('.jpg', '.jpeg', '.png', '.tif', '.tiff')
DATE_SRC = ['datetimeoriginal', 'datetimedigitized', 'mediacreatedate', 'datecreated',
            'createdate', 'filemodifydate']
# group names come back from exiftool as ExifIFD:/IFD0:/XMP:/QuickTime:/System:, so
# look tags up case-insensitively and by group preference rather than exact key
DATE_GROUP_RANK = {'exif': 0, 'exififd': 0, 'ifd0': 1, 'xmp': 2, 'quicktime': 3,
                   'track1': 4, 'trak': 4, 'system': 9}
# folder names that carry no event information
GENERIC = {'unsorted', 'canon unsorted', 'saved pictures', 'photos', 'misc', 'dump',
           'camera upload', 'imported', 'new folder', 'photos library'}


def junk(p):
    b = os.path.basename(p)
    return b.startswith('._') or b in ('.DS_Store', 'Thumbs.db', 'desktop.ini', '.localized')


def getd(rec):
    """Capture time, best source first: EXIF Original > Digitized > media create >
    XMP > file mtime. Returns (datetime string, is_real_capture_time)."""
    best = None
    for key, val in rec.items():
        if key == 'SourceFile' or not val:
            continue
        grp, _, tag = key.partition(':')
        tag = tag.lower()
        if tag not in DATE_SRC or 'gps' in key.lower():
            continue
        if isinstance(val, list):
            val = val[0]
        m = re.match(r'(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})',
                     str(val).replace('T', ' '))
        if not m:
            continue
        s = '-'.join(m.groups()[:3]) + ' ' + ':'.join(m.groups()[3:])
        if s <= '2000-01-01' or s > '2026-10-11':
            continue          # unset or badly set camera clocks (1970, 2070, ...)
        rank = (DATE_GROUP_RANK.get(grp.lower(), 5), DATE_SRC.index(tag))
        if best is None or rank < best[0]:
            best = (rank, s, grp.lower() != 'system')
    if best is None:
        return None, False
    return best[1], best[2]


def has_gps(rec):
    for key, val in rec.items():
        if 'gpslatitude' in key.lower() and val:
            return True
    return False


def clean_label(name):
    """Source folder name -> event label, same cleaning the original pass used."""
    s = re.sub(r'[\s\u00a0\u200b\ufeff]+', ' ', name).strip()
    s = re.sub(r'(?i)^\d+[\s._-]+', '', s)              # "001 Trip to.."
    s = re.sub(r'(?i)\bphotos?\s*[-–]\s*\d+\s*of\s*\d+\b', '', s)
    s = re.sub(r'(?i)[, ]*(dec|nov|oct|sep|apr|jan|feb|mar|may|jun|jul|aug)\.? '
               r'\d{4}$', r' \1', s)                      # trailing month + year
    s = re.sub(r'(?i)[, ]*(19|20)\d{2}$', '', s)         # trailing year
    s = re.sub(r'(?i)[, ]*(dec|nov|oct|sep|apr|jan|feb|mar|may|jun|jul|aug)\.?$',
               '', s)                                    # dangling month ("Trip Dec")
    s = re.sub(r'[\s]+', ' ', s).strip(' -_.')
    s = re.sub(r'(?i)[ ,\-]+(\d{1,2}[-.]\d{1,2}([-.\-]\d{2,4})?)$', '', s)  # "Gorge 22-05-2010"
    s = s.strip(' -_.,')
    if s.lower() in GENERIC or len(s) < 3:
        return None
    return s[:48]


def main():
    meta = {}
    for line in open(f'{W}/{META}'):
        r = json.loads(line)
        meta[r['SourceFile']] = r
    # the perceptual hits (dedup-candidates.json) were each settled by decoding
    # both sides and comparing pixels; only the RMSE-0 ones are dropped, and the
    # reason is recorded in pixel-verdicts.json next to this script.
    verdicts = json.load(open(f'{W}/pixel-verdicts.json'))
    drop = {(r['tree'], r['rel']) for r in verdicts['drop_pixel_identical']}
    cand = json.load(open(f'{W}/{BUCKETS}'))

    # live tree: which day folders exist, and how full they are
    live_day = defaultdict(list)
    live_max_n = {}
    for dirpath, dirnames, filenames in os.walk(LIB):
        rel = os.path.relpath(dirpath, LIB)
        if rel.count(os.sep) == 1 and re.match(r'\d{4}$', rel.split(os.sep)[0]):
            live_day[os.path.basename(rel)].append(rel)
        ns = [re.match(r'(\d{3})_', f) for f in filenames]
        mx = max([int(m.group(1)) for m in ns if m] or [0])
        live_max_n[dirpath] = max(live_max_n.get(dirpath, 0), mx)
    vid_day, vid_existing = defaultdict(list), set()
    for dirpath, _d, files in os.walk(VIDLIB):
        vid_existing.add(dirpath)
        ns = [re.match(r'(\d{3})_', f) for f in files]
        mx = max([int(m.group(1)) for m in ns if m] or [0])
        live_max_n[dirpath] = max(live_max_n.get(dirpath, 0), mx)
        if re.match(r'\d{4}$', os.path.relpath(dirpath, VIDLIB).split(os.sep)[0]) and files:
            vid_day[os.path.basename(dirpath)].append(os.path.relpath(dirpath, VIDLIB))

    plan, skipped = {}, {'junk': 0, 'grant': 0, 'dup': 0, 'undated': 0}
    for tag in ('new-image', 'new-video'):
        for src, rel, size in cand[tag]:
            if junk(rel):
                skipped['junk'] += 1
                continue
            if rel.startswith(GRANT):
                skipped['grant'] += 1
                continue
            if (tag == 'new-image' and (src, rel) in drop):
                skipped['dup'] += 1
                continue
            ap = os.path.join(ROOTS[src], rel)
            if not os.path.exists(ap):
                continue
            rec = meta.get(ap, {})
            dt, real = getd(rec)
            ext = os.path.splitext(rel)[1].lower()
            isvid = tag == 'new-video'
            # event label from the source folder
            parts = rel.split('/')
            fold = os.path.dirname(rel)
            if src in ZIP_PROV:
                # an archive entry: the directory it sat in inside the archive is
                # the event ("Elisa/Beachfront" -> "Elisa Beachfront"), because the
                # top level of those archives is a person, not an event
                top = ' '.join(p for p in rel.split('/')[:-2])
            elif src == 'Photosusa':
                top = parts[1] if parts[0] == 'photos' and len(parts) > 2 else (
                    parts[0] if parts[0] != 'photos' else '')
            else:
                top = ''
            label = clean_label(top or '')
            # a folder that states a year ("Garden Route Trip Dec 2010") says
            # nothing about a file the camera timed in a different year - those
            # recovered stragglers get a plain date folder rather than a wrong label
            fold_year = re.search(r'(?<!\d)((?:19|20)\d{2})(?!\d)', top or '')
            if label and dt and fold_year and fold_year.group(1) != dt[:4]:
                label, label_conflict = None, True
            else:
                label_conflict = False
            if dt is None:
                day, dd = None, None
                base = f'Undated/{label or os.path.basename(fold) or "Undated"}'
                target = f'{LIB}/{base}' if not isvid else f'{VIDLIB}/{base}'
            else:
                day = dt[:10]
                if isvid:
                    existing = sorted(vid_day.get(day, []))
                else:
                    existing = sorted(live_day.get(day, []))
                if existing:
                    # busiest existing folder for that day wins
                    best = max(existing, key=lambda d: len(os.listdir(os.path.join(
                        VIDLIB if isvid else LIB, d))))
                    target = (VIDLIB if isvid else LIB) + '/' + best
                else:
                    dd = f'{day[:4]}/{day}' + (f' {label}' if label else '')
                    target = (VIDLIB if isvid else LIB) + '/' + dd
            plan[ap] = {'src_tree': src, 'rel': rel, 'bytes': size, 'dt': dt, 'real': real,
                        'ext': ext, 'isvid': isvid, 'dir': target, 'gps': has_gps(rec),
                        'label_conflict': label_conflict, 'prov': PROV.get(ap, ''),
                        'dims': rec.get('Composite:ImageSize') or ''}
            if dt is None:
                skipped['undated'] += 1

    # sequence numbers inside each destination folder, continuing what is there
    seq = dict(live_max_n)
    taken = set()
    todo = sorted(plan.items(), key=lambda kv: (kv[1]['dir'], kv[1]['dt'] or '0000',
                                                os.path.basename(kv[0])))
    for ap, e in todo:
        d = e['dir']
        while True:
            seq[d] = seq.get(d, 0) + 1
            if e['dt']:
                stamp = e['dt'][:10].replace('-', '') + '-' + e['dt'][11:].replace(':', '')
            else:
                stamp = re.sub(r'[^\w.-]+', '_', os.path.splitext(os.path.basename(ap))[0])[:40]
            outext = '.mp4' if e['isvid'] else e['ext']
            dest = os.path.join(d, f'{seq[d]:03d}_{stamp}{outext}')
            if dest not in taken and not os.path.exists(dest):
                break
        taken.add(dest)
        e['dest'] = dest
        e['rel_dest'] = os.path.relpath(dest, VIDLIB if e['isvid'] else LIB)

    # The plan file is hand-edited, so writing it is the one destructive thing
    # this script does. Re-running it after an import has been completed produces
    # an empty plan (the source trees are drained) -- that overwrote the edited
    # plan twice on 2026-10-14. Keep the previous file, and refuse a shrink.
    _path = f"{W}/{PLAN}"
    _old = open(_path).read() if os.path.exists(_path) else ""
    try:
        _n_old = len(json.loads(_old)) if _old.strip() else 0
    except ValueError:
        _n_old = -1
    if PLAN_DRY:
        print(f"--dry: not writing {_path} ({len(plan)} records, "
              f"{_n_old} on disk)")
    elif len(plan) == 0 and _n_old > 0 and not os.environ.get("PLAN_ALLOW_SHRINK"):
        raise SystemExit(
            f"REFUSING to write {_path}: this run plans 0 records but the file holds "
            f"{_n_old}. A completed import drains the sources, so a bare re-run has "
            f"nothing left to plan. Edit the existing plan, or set PLAN_ALLOW_SHRINK=1.")
    else:
        if _old:
            with open(_path + ".prev", "w") as _fh:
                _fh.write(_old)
        with open(_path + ".tmp", "w") as _fh:
            json.dump({k: v for k, v in plan.items()}, _fh, indent=1)
        os.replace(_path + ".tmp", _path)
        print(f"wrote {_path}: {len(plan)} records "
              f"({_n_old} previous kept as {_path}.prev)")

    photos = [e for e in plan.values() if not e['isvid']]
    vids = [e for e in plan.values() if e['isvid']]
    print(f'skipped: junk {skipped["junk"]}  grant-backup(archive) {skipped["grant"]}  '
          f'pixel-dup {skipped["dup"]}')
    print(f'import photos: {len(photos)} files {sum(e["bytes"] for e in photos)/1e9:.2f} GB '
          f'in {len({e["dir"] for e in photos})} folders')
    print(f'import videos: {len(vids)} files {sum(e["bytes"] for e in vids)/1e9:.2f} GB '
          f'in {len({e["dir"] for e in vids})} folders')
    existing = set(live_max_n) | vid_existing
    new_dirs = sorted({e['dir'] for e in plan.values()} - existing)
    print(f'  of which brand-new folders: {len(new_dirs)} '
          f'({len([d for d in new_dirs if d.startswith(LIB)])} photo, '
          f'{len([d for d in new_dirs if d.startswith(VIDLIB)])} video)')
    print(f'  undated (no usable timestamp at all): {skipped["undated"]}')
    print('\nnew folders being created (sample):')
    for d in new_dirs[:12]:
        print('   +', os.path.relpath(d, LIB if d.startswith(LIB) else VIDLIB),
              f'{len([e for e in plan.values() if e["dir"] == d])} files')
    print('merging into existing day folders (sample):')
    merge = [d for d in {e['dir'] for e in plan.values()} if d in existing]
    for d in sorted(merge)[:8]:
        print('   =', os.path.relpath(d, LIB if d.startswith(LIB) else VIDLIB),
              f'+{len([e for e in plan.values() if e["dir"] == d])} files '
              f'(existing {len(os.listdir(d))})')
    n_conflict = sum(1 for e in plan.values() if e.get('label_conflict'))
    if n_conflict:
        print(f'  folder-name year disagreed with the camera time, label dropped: {n_conflict}')
    dates = [e['dt'] for e in plan.values() if e['dt']]
    if dates:
        print(f'\ndate range: {min(dates)} .. {max(dates)}; '
              f'EXIF-real: {sum(1 for e in plan.values() if e["real"])} '
              f'/{len(plan)}; GPS: {sum(1 for e in plan.values() if e["gps"])}')
    if os.environ.get('APPLY') == '1':
        cols = ['new', 'orig', 'src_tree', 'kind', 'change', 'bytes_before',
                'bytes_after', 'how', 'dt', 'folder']
        rows, bad, moved = [], [], []
        for ap, e in todo:
            if e['isvid']:
                continue
            os.makedirs(e['dir'], exist_ok=True)
            if os.path.exists(e['dest']):
                bad.append(e['dest'])
                continue
            shutil.move(ap, e['dest'])
            moved.append(ap)
            from_archive = e['src_tree'] in ZIP_PROV
            whence = ZIP_PROV[e['src_tree']] if from_archive else 'the hhd source tree'
            rows.append({'new': e['rel_dest'], 'orig': e['prov'] or e['rel'],
                         'src_tree': e['src_tree'],
                         'kind': 'photo', 'change': 'imported',
                         'bytes_before': e['bytes'], 'bytes_after': os.path.getsize(e['dest']),
                         'how': f'moved in from {whence}, bytes unchanged',
                         'dt': e['dt'] or '', 'folder': os.path.dirname(e['rel_dest'])})
        mpath = f'{W}/{MANIFEST}'
        fresh = not (os.path.exists(mpath) and os.path.getsize(mpath))
        with open(mpath, 'w' if fresh else 'a', newline='', encoding='utf-8') as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            if fresh:
                wr.writeheader()
            wr.writerows(rows)
        left = sum(1 for r in rows if not os.path.exists(os.path.join(LIB, r['new'])))
        gone = sum(1 for ap in moved if os.path.exists(ap))
        print(f'\nmoved {len(rows)} photos into the library; collisions {len(bad)}, '
              f'missing after move {left}, source still in place {gone}')


if __name__ == '__main__':
    main()
