#!/usr/bin/env python3
"""Decide, for every file in the hhd source trees, whether it is a duplicate.


Two rounds of evidence are combined:

  hashes_macphotos.jsonl / hashes_photosusa.jsonl
      the source trees, cut before the import moved anything out of them
  hashes_new.jsonl
      the library before the import (deleted, so the live library is re-hashed)
  hashes_backup.jsonl
      the 12 264 originals before the whole reorganisation, including the ones
      whose library copy and everything else has since been deleted

A source file is a duplicate when its bytes are somewhere safe: in the library
now, in the library as the result of this job's import, or identical to an old
original whose fate the manifests already record (survivor, video copy, or
deleted-with-proof). Nothing else is a duplicate.

  python3 account_sources.py         -> source-accounting.csv + summary
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/account_sources.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
from collections import Counter

W = '/home/lario/photos-reorg-work'
from paths import LIB
from paths import VIDLIB
from paths import HHD
HOLDOUT = 'photos/Grant Backup'


def blake(path):
    h = hashlib.blake2b()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def is_junk(name):
    return (name.startswith('._') or name in ('.DS_Store', 'Thumbs.db',
                                              'desktop.ini', '.AAE')
            or name.lower().endswith('.aae'))


def main():
    # --- what the source trees held before the import touched them
    src = {}
    for tag, fn in (('Mac Photos', 'hashes_macphotos.jsonl'),
                    ('Photosusa', 'hashes_photosusa.jsonl')):
        for line in open(f'{W}/{fn}'):
            d = json.loads(line)
            src[f'{tag}/{d["path"]}'] = d['hash']
    print(f'{len(src)} source-tree hashes from before the import')

    # --- what is in either library right now
    live = set()
    files = [os.path.join(dp, f) for root in (LIB, VIDLIB)
             for dp, _, fs in os.walk(root) for f in fs
             if not f.startswith('._')]
    print(f'hashing {len(files)} live library files...', flush=True)
    for p in files:
        live.add(blake(p))
    print(f'  {len(live)} distinct live hashes')

    # --- what this job imported, keyed by the bytes it read
    imported = set()
    for r in csv.DictReader(open(f'{W}/manifest-imports.csv', encoding='utf-8')):
        h = src.get(f"{r['src_tree']}/{r['orig']}")
        if h:
            imported.add(h)
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if r['orig'].startswith(('Mac Photos/', 'Photosusa/')):
            h = src.get(r['orig'])
            if h:
                imported.add(h)
    for line in open(f'{W}/hashes_zips.jsonl'):
        imported.add(json.loads(line)['hash'])
    print(f'  {len(imported)} hashes of content this job imported')

    # --- the old originals: survivors, video copies, deleted-with-proof
    survivors, gone = {}, set()
    for r in csv.DictReader(open(f'{W}/manifest-moves.csv', encoding='utf-8')):
        for k in ('orig', 'backup'):
            if r.get(k):
                survivors[r[k]] = os.path.join(LIB, r['new'])
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if not r['orig'].startswith(('Mac Photos/', 'Photosusa/')):
            survivors[r['orig']] = os.path.join(VIDLIB, r['dest'])
    for r in csv.DictReader(open(f'{W}/manifest-deletes.csv', encoding='utf-8')):
        gone.add(r['orig'])
        if r.get('backup'):
            gone.add(r['backup'])
    accounted_old = {}
    for line in open(f'{W}/hashes_backup.jsonl'):
        d = json.loads(line)
        p = d['path']
        if p in survivors and os.path.exists(survivors[p]):
            accounted_old[d['hash']] = f'survivor {p} -> {survivors[p]}'
        elif p in gone:
            accounted_old[d['hash']] = f'old original {p}, deleted with proof'
    print(f'  {len(accounted_old)} old-original hashes already accounted for')

    # --- archive contents, staged on disk because the archives cannot be read
    #     in place (the zip's own entry name is not a path)
    staged = json.load(open(f'{W}/zip-staging.json'))
    by_tree = {}
    for entry, info in staged.items():
        arc, _, rel = entry.partition('::')
        by_tree.setdefault(arc, []).append((rel, info))

    def zip_proof(arc_path, key):
        """'empty' when every member's bytes are safe, else the members that
        are not. Member bytes are read from the staged copy made by
        extract_zips.py, because an entry inside a zip is not a path."""
        members = by_tree.get(key, [])
        missing = []
        for rel, info in members:
            base = rel.rsplit('/', 1)[-1]
            if is_junk(base):
                info['why'] = 'AppleDouble junk'
                continue
            sp = os.path.join(W, info['dest'])
            if not os.path.exists(sp):
                missing.append((rel, 'not staged'))
                continue
            h = blake(sp)
            why = ('live now' if h in live else
                   'imported by this job' if h in imported else
                   accounted_old.get(h))
            if why:
                info['why'] = why
            else:
                missing.append((rel, sp))
        return ('empty' if not missing else 'unique-members', members, missing)

    rows, tally = [], Counter()
    for tree in ('Mac Photos', 'Photosusa'):
        for dp, dirs, fs in os.walk(f'{HHD}/{tree}'):
            rel_dir = os.path.relpath(dp, f'{HHD}/{tree}')
            if rel_dir == HOLDOUT or rel_dir.startswith(HOLDOUT + '/'):
                continue
            for f in fs:
                rel = os.path.join(rel_dir, f) if rel_dir != '.' else f
                ap = os.path.join(dp, f)
                size = os.path.getsize(ap)
                key = f'{tree}/{rel}'
                if is_junk(f):
                    if f.startswith('._') and os.path.exists(
                            os.path.join(dp, f[2:])):
                        cat = 'junk-appledouble'
                    else:
                        cat = 'junk-name'
                elif '/VIDEO_TS/' in rel or '/AUDIO_TS/' in rel or rel.endswith(
                        ('/VIDEO_TS', '/AUDIO_TS')):
                    cat = 'dvd-scaffold'
                elif f.lower().endswith('.aae'):
                    cat = 'junk-aae'
                else:
                    h = src.get(key)
                    if not h or size == 0:
                        cat = 'zero-or-unindexed'
                    elif h in live:
                        cat = 'dup-byte-live'
                    elif h in imported:
                        cat = 'dup-imported-twin'
                    elif h in accounted_old:
                        cat = 'dup-original-accounted'
                    elif f.lower().endswith('.zip'):
                        state, members, missing = zip_proof(ap, f)
                        cat = ('dup-zip-empty' if state == 'empty'
                               else f'zip-{len(missing)}-unique-members')
                    else:
                        cat = 'UNIQUE'
                tally[cat] += 1
                rows.append({'source_file': key, 'bytes': size, 'category': cat})

    if not rows:
        raise SystemExit(f'no files found outside {HOLDOUT} under {HHD}: the source '
                         'trees are drained. Refusing to overwrite '
                         'source-accounting.csv, which is the record of what was '
                         'there before the deletion.')
    with open(f'{W}/source-accounting.csv', 'w', newline='', encoding='utf-8') as fh:
        wr = csv.DictWriter(fh, fieldnames=['source_file', 'bytes', 'category'])
        wr.writeheader()
        wr.writerows(rows)

    print(f'\nfiles outside Grant Backup: {len(rows)}')
    for cat, n in tally.most_common():
        b = sum(int(r['bytes']) for r in rows if r['category'] == cat) / 2**30
        print(f'  {cat:26} {n:6}  {b:8.2f} GiB')
    del_b = sum(int(r['bytes']) for r in rows
                if r['category'].startswith(('dup', 'junk'))) / 2**30
    print(f'\ndeletable as duplicate or junk: {del_b:.2f} GiB')
    print('source-accounting.csv written')


if __name__ == "__main__":
    main()
