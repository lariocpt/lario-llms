#!/usr/bin/env python3
"""Re-derive the archive conclusion from scratch.


Every file extracted from Archive.zip and Marie.zip is re-hashed now and traced
to content that is safe today. Three independent sources of proof, none of them
the ledger being checked:

  the two libraries, re-hashed
  the pre-import index of the hhd source trees, for the originals of everything
      this job imported (those source files are deleted; the index is their only
      remaining record)
  the pre-reorganisation originals index, for content whose fate the older
      manifests already record

  python3 verify_archive_claim.py
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/verify_archive_claim.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

W = '/home/lario/photos-reorg-work'
from paths import LIB
from paths import VIDLIB


def blake(path):
    h = hashlib.blake2b()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    staged = {}
    for line in open(f'{W}/zip-provenance.jsonl'):
        d = json.loads(line)
        staged[d['staged']] = d['provenance']

    paths = list(staged)
    print(f'{len(paths)} staged archive entries, re-hashing...', flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        hashes = list(ex.map(blake, paths))

    live = {}
    files = [os.path.join(dp, f) for root in (LIB, VIDLIB)
             for dp, _, fs in os.walk(root) for f in fs if not f.startswith('._')]
    print(f'hashing {len(files)} live library files...', flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for p, h in zip(files, ex.map(blake, files)):
            live.setdefault(h, p)

    src_hash = {}
    for tag, fn in (('Mac Photos', 'hashes_macphotos.jsonl'),
                    ('Photosusa', 'hashes_photosusa.jsonl')):
        for line in open(f'{W}/{fn}'):
            d = json.loads(line)
            src_hash[f'{tag}/{d["path"]}'] = d['hash']

    imported = {}
    hits = 0
    for r in csv.DictReader(open(f'{W}/manifest-imports.csv', encoding='utf-8')):
        k = f"{r['src_tree']}/{r['orig']}"
        if k in src_hash:
            hits += 1
            imported[src_hash[k]] = (r['src_tree'], r['orig'], r['new'])
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if r['orig'] in src_hash:
            imported[src_hash[r['orig']]] = ('?', r['orig'], r['dest'])
    # a silent zero here is exactly the defect that produced the wrong archive
    # finding the first time, so refuse rather than report an empty set
    print(f'  imported originals resolved from the manifest: {hits} photo rows, '
          f'{len(imported)} hashes')
    if hits < 4000:
        raise SystemExit(f'import lookups broken: only {hits} rows resolved')

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
    old = {}
    for line in open(f'{W}/hashes_backup.jsonl'):
        d = json.loads(line)
        p = d['path']
        if p in survivors and os.path.exists(survivors[p]):
            old[d['hash']] = f'old original {p} -> {survivors[p]}'
        elif p in gone:
            old[d['hash']] = f'old original {p}, deleted with proof'

    tally, unrepresented = Counter(), []
    for path, h in zip(paths, hashes):
        entry = staged[path]
        base = entry.rsplit('::', 1)[-1].rsplit('/', 1)[-1]
        if base.startswith('._') or base in ('.DS_Store', 'Thumbs.db'):
            tally['AppleDouble / system junk'] += 1
            continue
        if h in live:
            tally['byte-identical to a library file that exists now'] += 1
        elif h in imported:
            tally['the original of a photo or video this job imported'] += 1
        elif h in old:
            tally['an old original already accounted for in the manifests'] += 1
        else:
            tally['UNREPRESENTED'] += 1
            unrepresented.append((entry, path))

    for k, n in tally.most_common():
        print(f'  {n:5}  {k}')
    print(f'\n{sum(tally.values())} staged entries, {tally["UNREPRESENTED"]} '
          f'not represented anywhere')
    for e, d in unrepresented[:20]:
        print(f'   UNREPRESENTED {e}  ({d})')


if __name__ == "__main__":
    main()
