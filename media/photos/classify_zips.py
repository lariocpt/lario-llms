#!/usr/bin/env python3
"""Classify the staged archive contents against everything that already exists.


Same question analyze_sources.py asked for the two loose trees, answered for the
files expanded out of Archive.zip and Marie.zip: is these bytes already in the
library, already covered by a library copy that was recompressed, kept outside
the library on purpose (Grant Backup), or genuinely new?

Every staged file gets one row in zip-ledger.csv with its proof. The genuinely
new images and videos go into new-candidates-zips.json, in the bucket format
plan_import.py reads, and a provenance column carries the archive and the entry
path inside it so the import manifest can point back at the real original.

  mode=plan   (default) classify and write the candidate buckets
  mode=final  re-run after the import: rows that were imported are resolved
              against the library and the import manifests

usage: python3 classify_zips.py [plan|final]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/classify_zips.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import LIB
from paths import VIDLIB
from paths import HHD, named_sources
# Unset LARIO_SRC_DIRS gives exactly the two trees this file has always used. Registered
# the way plan_import.py registers them: these are the external drives being merged in,
# so a pass that keeps pointing at last batch's trees answers 0 and looks clean while
# the drive actually attached is never read.
try:
    SRC_ROOTS = named_sources('LARIO_SRC_DIRS',
                              {'Mac Photos': f'{HHD}/Mac Photos', 'Photosusa': f'{HHD}/Photosusa'})
except ValueError as bad:
    raise SystemExit(f'refused: {bad}')
STAGE = f'{W}/zip-extract'
GRANT = 'photos/Grant Backup'
IMG = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heic')
VID = ('.mov', '.mp4', '.avi', '.3gp', '.mpg', '.mpeg', '.dv', '.vob', '.m4v',
       '.wmv', '.flv', '.mts')
JUNKNAME = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.localized'}
CSV_COLS = ['tag', 'staged_rel', 'provenance', 'bytes', 'kind', 'status', 'imported_as',
            'proof']


def blake(path):
    # blake2b with its default 64-byte digest: every index this job cut
    # (hashes_new, hashes_backup, hashes_macphotos, hashes_photosusa) uses that,
    # and a shorter digest silently matches nothing.
    h = hashlib.blake2b()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def index_jsonl(fn):
    """hash -> one path that has it."""
    out = {}
    with open(f'{W}/{fn}') as fh:
        for line in fh:
            d = json.loads(line)
            out.setdefault(d['hash'], d['path'])
    return out


def main(mode):
    staging = json.load(open(f'{W}/zip-staging.json'))
    prov = {}
    for line in open(f'{W}/zip-provenance.jsonl'):
        d = json.loads(line)
        prov[d['staged']] = d['provenance']

    live = {}
    if mode == 'plan':
        for fn, base in (('hashes_new.jsonl', 'library'),
                         ('hashes_livevideos.jsonl', 'video library')):
            for h, p in index_jsonl(fn).items():
                live.setdefault(h, f'{base}:{p}')
        # the libraries as they physically are now (imported and recompressed)
        fresh = []
        for root, tag in ((LIB, 'library'), (VIDLIB, 'video library')):
            for dp, _d, fs in os.walk(root):
                for f in fs:
                    if not f.startswith('._'):
                        fresh.append((os.path.join(dp, f), tag))
        print(f'hashing {len(fresh)} live files...', flush=True)
        with open(f'{W}/hashes_live_now.jsonl', 'w') as fh:
            for i, (p, tag) in enumerate(fresh, 1):
                h = blake(p)
                live[h] = f'{tag}:{p}'
                fh.write(json.dumps({'hash': h, 'abs': p, 'lib': tag}) + '\n')
                if i % 3000 == 0:
                    print(f'  {i}/{len(fresh)}', flush=True)
    else:
        for line in open(f'{W}/hashes_live_now.jsonl'):
            d = json.loads(line)
            live[d['hash']] = f'{d["lib"]}:{d["abs"]}'

    orig = index_jsonl('hashes_backup.jsonl')          # old original -> hash
    survivors, deleted = {}, set()
    with open(f'{W}/manifest-moves.csv', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            for k in ('orig', 'backup'):
                if r.get(k):
                    survivors[r[k]] = os.path.join(LIB, r['new'])
    with open(f'{W}/manifest-deletes.csv', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            deleted.add(r['orig'])
            if r.get('backup'):
                deleted.add(r['backup'])
    video_live = {}
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if not r['orig'].startswith(('Mac Photos/', 'Photosusa/', 'Archive.zip/',
                                    'Marie.zip')):
            video_live[r['orig']] = os.path.join(VIDLIB, r['dest'])
    # hhd videos this job already transcoded: their loose source files were deleted
    # after the transcode, so the manifest row is the only record left of the bytes
    # an archive entry can be compared against.
    vid_src = {}
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if r['orig'].startswith(('Mac Photos/', 'Photosusa/')) and os.path.exists(
                os.path.join(VIDLIB, r['dest'])):
            vid_src[(os.path.basename(r['orig']).lower(),
                     int(float(r['in_bytes'])))] = f'{VIDLIB}/{r["dest"]}'

    # files imported by this job: their bytes as they were before the move
    src_hash = {}
    for tag, fn in (('Mac Photos', 'hashes_macphotos.jsonl'),
                    ('Photosusa', 'hashes_photosusa.jsonl')):
        for line in open(f'{W}/{fn}'):
            d = json.loads(line)
            src_hash[f'{tag}/{d["path"]}'] = d['hash']
    imports = {}
    for r in csv.DictReader(open(f'{W}/manifest-imports.csv', encoding='utf-8')):
        imports[f"{r['src_tree']}/{r['orig']}"] = r
    imported_hash = {}
    for key, r in imports.items():
        h = src_hash.get(key)
        if h:
            imported_hash[h] = f'{key} -> {LIB}/{r["new"]} ({r["how"]})'

    # what the earlier accounting decided about each loose source file
    account = {}
    for r in csv.DictReader(open(f'{W}/source-accounting.csv', encoding='utf-8')):
        account[r['source_file']] = r['category']
    grant_hash, src_live_hash = {}, {}
    for key, h in src_hash.items():
        tree, _, rel = key.partition('/')
        if rel.startswith(GRANT):
            grant_hash.setdefault(h, key)
        elif account.get(key, '').startswith('dup') or account.get(key, '') in (
                'dvd-scaffold',):
            src_live_hash.setdefault(h, f'{key} [{account[key]}]')

    # stage hashes
    staged = {}
    hz = open(f'{W}/hashes_zips.jsonl', 'w')
    for tag, info in staging.items():
        root = info['dir']
        for dp, _d, fs in os.walk(root):
            for f in fs:
                if f.startswith('._') or f in JUNKNAME:
                    continue
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, root)
                h = blake(p)
                staged[(tag, rel)] = (h, os.path.getsize(p), p)
                hz.write(json.dumps({'path': f'{tag}/{rel}', 'size': os.path.getsize(p),
                                     'hash': h}) + '\n')
    hz.close()
    print(f'{len(staged)} staged files hashed')

    # resolve previous runs (final mode): what this job already imported
    zip_imports, zip_videos = {}, {}
    for r in csv.DictReader(open(f'{W}/manifest-imports.csv', encoding='utf-8')):
        if r['src_tree'] in staging:
            zip_imports[r['orig']] = r
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if r['orig'].startswith(tuple(f'{t}.zip::' for t in staging)):
            zip_videos[r['orig']] = r

    rows, buckets = [], {t: defaultdict(list) for t in ('new-image', 'new-video')}
    seen_hash = {}
    stats = defaultdict(lambda: [0, 0])
    for (tag, rel), (h, size, path) in sorted(staged.items()):
        ext = os.path.splitext(rel)[1].lower()
        kind = 'image' if ext in IMG else ('video' if ext in VID else 'other')
        source = prov.get(path, f'{tag}.zip::{rel}')
        status = proof = imported_as = ''
        if mode == 'final' and source in zip_imports:
            r = zip_imports[source]
            status, imported_as = 'imported', f'{LIB}/{r["new"]}'
            proof = f'imported into the library, {r["how"]}'
        elif mode == 'final' and source in zip_videos:
            r = zip_videos[source]
            status, imported_as = 'imported', f'{VIDLIB}/{r["dest"]}'
            proof = f'transcoded into the video library, mode={r["mode"]}'
        elif h in live:
            status, proof = 'dup-live-byte', live[h]
        elif h in imported_hash:
            status, proof = 'dup-imported-twin', imported_hash[h]
        elif h in grant_hash:
            status, proof = 'kept-in-grant-archive', grant_hash[h]
        elif h in src_live_hash:
            status, proof = 'dup-source-represented', src_live_hash[h]
        elif h in orig and orig[h] in survivors:
            status, proof = 'dup-original-live', f'{orig[h]} -> {survivors[orig[h]]}'
        elif h in orig and orig[h] in video_live:
            status, proof = 'dup-video-live', f'{orig[h]} -> {video_live[orig[h]]}'
        elif kind == 'video' and (os.path.basename(rel).lower(), size) in vid_src:
            status, proof = 'dup-video-imported', (
                'the same source path and byte count were transcoded into the '
                f'video library as {vid_src[(os.path.basename(rel).lower(), size)]}')
        elif h in orig and orig[h] in deleted:
            status, proof = 'dup-deleted-original', f'hash of {orig[h]}, deleted with proof'
        elif h in seen_hash:
            status, proof = 'dup-staging-twin', seen_hash[h]
        elif kind == 'image':
            status = 'new-image'
            seen_hash[h] = f'{tag}/{rel}'
            buckets['new-image'][tag].append([tag, rel, size])
        elif kind == 'video':
            status = 'new-video'
            seen_hash[h] = f'{tag}/{rel}'
            buckets['new-video'][tag].append([tag, rel, size])
        else:
            status = 'new-other:' + (ext.lstrip('.') or 'noext')
        rows.append([tag, rel, source, size, kind, status, imported_as, proof])
        stats[status][0] += 1
        stats[status][1] += size

    rows.sort(key=lambda r: (r[5], -r[3]))
    with open(f'{W}/zip-ledger.csv', 'w', newline='', encoding='utf-8') as fh:
        wr = csv.writer(fh)
        wr.writerow(CSV_COLS)
        wr.writerows(rows)

    if mode == 'plan':
        cand = {'new-image': [], 'new-video': []}
        for tag in staging:
            cand['new-image'] += buckets['new-image'].get(tag, [])
            cand['new-video'] += buckets['new-video'].get(tag, [])
        json.dump(cand, open(f'{W}/new-candidates-zips.json', 'w'), indent=1)
        extra = {t: staging[t]['dir'] for t in staging}
        json.dump({'roots': extra,
                   'prov': {t: f"{staging[t]['tree']}/{staging[t]['zip_rel']}"
                            for t in staging}},
                  open(f'{W}/zip-roots.json', 'w'), indent=1)
        print('wrote new-candidates-zips.json, zip-roots.json')

    print(f'\n{"status":26} {"files":>6} {"MiB":>9}')
    for k, (n, b) in sorted(stats.items(), key=lambda x: -x[1][1]):
        print(f'{k:26} {n:6} {b / 2**20:9.1f}')
    print(f'\n{len(rows)} rows -> zip-ledger.csv')


main('final' if 'final' in sys.argv[1:] else 'plan')
