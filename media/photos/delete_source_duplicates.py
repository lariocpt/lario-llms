#!/usr/bin/env python3
"""Delete from the two source trees only what is proven to be available elsewhere,

and the Apple junk. Every check is made again at delete time, not trusted from the
accounting run:

  junk-*          AppleDouble (._*), .DS_Store, Thumbs.db, .aae edit sidecars
  dup-*           the file's bytes right now still equal the bytes the accounting
                  saw, and those bytes are represented by a live library file, by
                  an import this job made, or by an old original that either
                  survived into the library or was itself deleted with proof
  dvd-scaffold    DVD menus, IFO and BUP around a disc whose main title is in the
                  video library (the owner's decision was one MP4 per disc)
  Archive.zip /
  Marie.zip       every entry of the archive is represented, according to
                  check_zips.py (zip-verified.json) and this run's own recount

photos/Grant Backup is a third party's photography archive and is never touched
here; nothing else in the tree is deleted either if a check does not hold.
Empty directories are pruned afterwards, and every deletion is written to
manifest-source-deletes.csv.

  DRY=1  only report
usage: python3 delete_source_duplicates.py
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/delete_source_duplicates.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import LIB
from paths import VIDLIB
from paths import HHD
ROOTS = {'Mac Photos': f'{HHD}/Mac Photos', 'Photosusa': f'{HHD}/Photosusa'}
GRANT = 'photos/Grant Backup'
JUNKCAT = {'junk-appledouble': '._* / .DS_Store / Thumbs.db resource fork',
           'junk-name': 'Thumbs.db / .DS_Store',
           'junk-aae': '.aae edit sidecar of a Live Photo'}
KEEP = {'grant-archive'}
VID_PREFIX = ('Mac Photos/', 'Photosusa/', 'Archive.zip::', 'Marie.zip::')
COLS = ['source_file', 'bytes', 'category', 'gate', 'verified', 'deleted']


def blake(path):
    # blake2b's default 64-byte digest, the one every index in this job uses
    h = hashlib.blake2b()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    dry = os.environ.get('DRY') == '1'
    rows = list(csv.DictReader(open(f'{W}/source-accounting.csv', encoding='utf-8')))
    print(f'{len(rows)} accounted source files')

    # --- what exists in the libraries right now ---------------------------------
    live = set()
    files = []
    for root in (LIB, VIDLIB):
        files += [os.path.join(dp, f) for dp, _, fs in os.walk(root)
                  for f in fs if not f.startswith('._')]
    print(f'hashing {len(files)} live library files...', flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for h in ex.map(blake, files):
            live.add(h)
    print(f'  {len(live)} distinct live hashes')

    # --- bytes this job moved into the libraries, as they were before the move ---
    src_hash = {}
    for tag, fn in (('Mac Photos', 'hashes_macphotos.jsonl'),
                    ('Photosusa', 'hashes_photosusa.jsonl')):
        for line in open(f'{W}/{fn}'):
            d = json.loads(line)
            src_hash[f'{tag}/{d["path"]}'] = d['hash']
    zpath_hash = {}
    for line in open(f'{W}/hashes_zips.jsonl'):
        d = json.loads(line)
        zpath_hash[d['path']] = d['hash']
    staged_by_prov = {}
    for line in open(f'{W}/zip-provenance.jsonl'):
        d = json.loads(line)
        staged_by_prov[d['provenance']] = os.path.relpath(d['staged'],
                                                          f'{W}/zip-extract')
    imported = {}
    for r in csv.DictReader(open(f'{W}/manifest-imports.csv', encoding='utf-8')):
        key = f"{r['src_tree']}/{r['orig']}"
        h = src_hash.get(key) or zpath_hash.get(staged_by_prov.get(r['orig'], ''))
        if h:
            imported[h] = f'{LIB}/{r["new"]}'
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        h = zpath_hash.get(staged_by_prov.get(r['orig'], ''))
        if h:
            imported[h] = f'{VIDLIB}/{r["dest"]}'
    print(f'  {len(imported)} imported originals')

    # --- the old originals index and where the reorganisation left those paths --
    survivors, deleted = {}, set()
    for r in csv.DictReader(open(f'{W}/manifest-moves.csv', encoding='utf-8')):
        for k in ('orig', 'backup'):
            if r.get(k):
                survivors[r[k]] = os.path.join(LIB, r['new'])
    for r in csv.DictReader(open(f'{W}/manifest-deletes.csv', encoding='utf-8')):
        deleted.add(r['orig'])
        if r.get('backup'):
            deleted.add(r['backup'])
    video_orig = {}
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if not r['orig'].startswith(VID_PREFIX):
            video_orig[r['orig']] = os.path.join(VIDLIB, r['dest'])
    old = {}
    for line in open(f'{W}/hashes_backup.jsonl'):
        d = json.loads(line)
        p = d['path']
        if p in survivors and os.path.exists(survivors[p]):
            old.setdefault(d['hash'], f'library copy {survivors[p]}')
        elif p in video_orig and os.path.exists(video_orig[p]):
            old.setdefault(d['hash'], f'video library copy {video_orig[p]}')
        elif p in deleted:
            old.setdefault(d['hash'], f'{p}, deleted with proof')
    print(f'  {len(old)} old-original hashes resolved')

    # --- the discs whose main title made it into the video library --------------
    discs = [r['orig'] for r in csv.DictReader(open(f'{W}/manifest-videos.csv',
                                                    encoding='utf-8'))
             if 'VIDEO_TS' in r['orig'] and os.path.exists(
                 os.path.join(VIDLIB, r['dest']))]

    def represented(h):
        if h in live:
            return 'live library file has these bytes'
        if h in imported:
            return f'this job imported these bytes as {imported[h]}'
        if h in old:
            return f'old original accounted for: {old[h]}'
        return None

    # --- the archives, only if check_zips.py cleared them -----------------------
    cleared = set(json.load(open(f'{W}/zip-verified.json'))) if os.path.exists(
        f'{W}/zip-verified.json') else set()
    evidence = json.load(open(f'{W}/zip-evidence.json')) if os.path.exists(
        f'{W}/zip-evidence.json') else {}
    # the near-duplicate calls that were settled by comparing pixels
    verdicts = {(v['tree'], v['rel']): v for v in
                json.load(open(f'{W}/pixel-verdicts.json'))['drop_pixel_identical']}
    print(f'  archives cleared by check_zips.py: {sorted(cleared) or "none"}')

    out = []
    for r in rows:
        key, cat = r['source_file'], r['category']
        tree, _, rel = key.partition('/')
        ap = os.path.join(ROOTS[tree], rel)
        if not os.path.exists(ap):
            out.append([key, r['bytes'], cat, 'already absent', 'yes', 'no'])
            continue
        gate = verified = None
        if cat in JUNKCAT:
            base = os.path.basename(ap)
            want = (JUNKCAT[cat].startswith('._') and base.startswith('._')) or (
                base in ('.DS_Store', 'Thumbs.db', 'desktop.ini') or
                base.lower().endswith('.aae'))
            gate, verified = JUNKCAT[cat], 'yes' if want else 'NAME-CHANGED'
        elif cat == 'dvd-scaffold':
            hit = next((d for d in discs if key.startswith(d.rsplit('/VIDEO_TS', 1)[0])
                        or key.startswith(os.path.dirname(
                            os.path.dirname(d)) + '/')), None)
            gate = ('disc scaffolding (menus/IFO/BUP/extra VOB); main title -> '
                    f'{hit}' if hit else 'no imported disc MP4 covers this file')
            verified = 'yes' if hit else 'NO DISC'
        elif cat == 'dup-perceptual':
            v = verdicts.get((tree, rel))
            if v:
                tgt = v['against']
                tgt = tgt if tgt.startswith('/') else os.path.join(
                    VIDLIB if tgt.startswith('videos/') else LIB, tgt)
                if os.path.exists(tgt):
                    gate = f'pixels identical (RMSE {v["rmse"]}) to live {tgt}'
                    verified = 'yes'
                else:
                    gate, verified = f'live twin of this verdict is gone: {tgt}', 'no'
            else:
                gate, verified = 'no pixel verdict on record for this file', 'no'
        elif cat.startswith('dup'):
            h = blake(ap)
            rep = represented(h)
            gate = rep or 'NOT REPRESENTED ANYWHERE'
            verified = 'yes' if rep else 'NO PROOF'
        elif cat == 'zip-proven-empty':
            if key in cleared:
                ev = evidence[key]
                gate = (f'all {ev["entries"]} archive entries represented '
                        f'({", ".join(f"{n} {c}" for c, n in ev["categories"].items())})')
                verified = 'yes'
            else:
                gate, verified = 'archive still has unique entries', 'no'
        elif cat in KEEP:
            continue
        else:
            gate, verified = f'not a duplicate category ({cat})', 'no'
        out.append([key, r['bytes'], cat, gate[:160], verified,
                    'pending' if verified == 'yes' else 'no'])

    todo = [r for r in out if r[5] == 'pending']
    blocked = [r for r in out if r[4] != 'yes']
    nbytes = sum(int(r[1]) for r in todo)
    by_cat = {}
    for r in todo:
        c = by_cat.setdefault(r[2], [0, 0])
        c[0] += 1
        c[1] += int(r[1])
    print(f'\n{"category":22} {"files":>6} {"MiB":>10}')
    for k, (n, b) in sorted(by_cat.items(), key=lambda x: -x[1][1]):
        print(f'{k:22} {n:6} {b / 2**20:10.1f}')
    print(f'{len(todo)} files, {nbytes / 2**30:.2f} GiB to delete')
    if blocked:
        print(f'\nNOT deleted, {len(blocked)} files:')
        for r in blocked[:20]:
            print(f'   {r[4]:12} {r[0][-72:]}  {r[3][:70]}')

    if dry:
        print('\nDRY=1, nothing deleted')
        return
    done = 0
    for r in out:
        if r[5] != 'pending':
            continue
        tree, _, rel = r[0].partition('/')
        ap = os.path.join(ROOTS[tree], rel)
        try:
            os.unlink(ap)
            r[5] = 'yes'
            done += 1
        except OSError as e:
            r[5] = f'FAILED: {e}'
            print('  delete failed', ap, e)
    print(f'deleted {done} files')

    # --- prune directories that are now empty -----------------------------------
    pruned = 0
    for root in ROOTS.values():
        for dp, ds, fs in os.walk(root, topdown=False):
            if dp.startswith(GRANT) or os.path.relpath(dp, root).startswith(GRANT):
                continue
            if not os.listdir(dp):
                try:
                    os.rmdir(dp)
                    pruned += 1
                except OSError:
                    pass
    print(f'pruned {pruned} now-empty directories')

    with open(f'{W}/manifest-source-deletes.csv', 'w', newline='',
              encoding='utf-8') as fh:
        wr = csv.writer(fh)
        wr.writerow(COLS)
        wr.writerows(out)
    print(f'manifest-source-deletes.csv: {len(out)} rows')

    left = {}
    for tree, root in ROOTS.items():
        for dp, ds, fs in os.walk(root):
            for f in fs:
                rel = os.path.relpath(os.path.join(dp, f), root)
                grp = 'Grant Backup' if rel.startswith(GRANT) else 'other'
                c = left.setdefault(f'{tree}/{grp}', [0, 0])
                c[0] += 1
                c[1] += os.path.getsize(os.path.join(dp, f))
    print('\nleft in the source trees:')
    for k, (n, b) in sorted(left.items()):
        print(f'  {k:28} {n:6} files {b / 2**30:8.2f} GiB')


if __name__ == "__main__":
    main()
