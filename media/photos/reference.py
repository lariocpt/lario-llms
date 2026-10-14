#!/usr/bin/env python3
"""The one way this job builds a set of bytes that are already safe.

Three scripts needed the same reference set and each wrote its own, which is how
one of them ended up hashing with a 32-byte digest and matching nothing. Build it
here only.

  reference() -> {hash: 'how these bytes are safe, with a path'}

Sources of proof, strongest first as they are added (the first one wins):

  live            a file in either library as it sits on disk right now
  imported        the bytes this job moved into the library, recovered from the
                  index cut before the move, so a later q85 recompression of the
                  library copy does not hide the original
  old-original    a pre-reorganisation original whose fate the older manifests
                  record: survivor with a library copy, video copy, or deleted
                  with proof

Nothing else counts. A hash that is not in here is content this job does not
have anywhere, and nothing carrying it may be deleted.
"""
import csv
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor

W = '/home/lario/photos-reorg-work'
from paths import LIB
from paths import VIDLIB
from paths import HHD
HOLDOUT = 'photos/Grant Backup'


def blake(path):
    """blake2b, full 64-byte digest - the digest every index in this job uses."""
    h = hashlib.blake2b()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def blake_bytes(blob):
    return hashlib.blake2b(blob).hexdigest()


def file_hashes(paths, cache=f'{W}/file-hash-cache.json'):
    """{path: hash} with a cache keyed on (size, mtime_ns), so a rerun over an
    unchanged tree costs a stat, not a re-hash. Correctness does not depend on
    the cache: a changed or new file is re-hashed, and a file that no longer
    exists is simply not in the result - so a deleted library file can never be
    offered as proof that content is still live."""
    stored = {}
    if os.path.exists(cache):
        with open(cache) as fh:
            stored = json.load(fh)
    out, todo = {}, []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        key = f'{st.st_size}:{st.st_mtime_ns}'
        hit = stored.get(p)
        if hit and hit[0] == key:
            out[p] = hit[1]
        else:
            todo.append((p, key))
    if todo:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for (p, key), h in zip(todo, ex.map(blake, [t[0] for t in todo])):
                out[p] = h
                stored[p] = [key, h]
        tmp = cache + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump({k: v for k, v in stored.items()
                       if k in out or os.path.exists(k)}, fh)
        os.replace(tmp, cache)
    return out


def tree_files(root):
    files = []
    for dp, dirs, fs in os.walk(root):
        for f in fs:
            if f.startswith('._') or f in ('.DS_Store', 'Thumbs.db'):
                continue
            files.append(os.path.join(dp, f))
    return files


def source_index():
    """{'<tree>/<path as it was>': hash} for the hhd trees, as they were before
    the import moved their files out. Those files are gone; this is their only
    remaining record."""
    out = {}
    for tag, fn in (('Mac Photos', 'hashes_macphotos.jsonl'),
                    ('Photosusa', 'hashes_photosusa.jsonl')):
        with open(f'{W}/{fn}') as fh:
            for line in fh:
                d = json.loads(line)
                out[f'{tag}/{d["path"]}'] = d['hash']
    return out


def reference(holdout_grant=True):
    known = {}

    def add(h, note):
        known.setdefault(h, note)

    for root in (LIB, VIDLIB):
        for p, h in file_hashes(tree_files(root)).items():
            add(h, f'live now: {p}')

    src = source_index()
    hits = 0
    with open(f'{W}/manifest-imports.csv', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            h = src.get(f"{r['src_tree']}/{r['orig']}")
            if h:
                hits += 1
                add(h, f'imported as {LIB}/{r["new"]}')
    with open(f'{W}/manifest-videos.csv', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            h = src.get(r['orig'])
            if h and os.path.exists(os.path.join(VIDLIB, r['dest'])):
                add(h, f'transcoded as {VIDLIB}/{r["dest"]}')
    # the import manifest is 4 027 photo rows; a lookup that resolves far fewer
    # means the keys are wrong, which is the defect that produced a wrong
    # conclusion about the archives once already
    if hits < 4000:
        raise SystemExit(f'reference set broken: only {hits}/4027 import rows '
                         'resolved against the pre-import source index')

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
    video_paths = {}
    with open(f'{W}/manifest-videos.csv', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if not r['orig'].startswith(('Mac Photos/', 'Photosusa/', 'Archive.zip',
                                         'Marie.zip')):
                video_paths[r['orig']] = os.path.join(VIDLIB, r['dest'])
    with open(f'{W}/hashes_backup.jsonl') as fh:
        for line in fh:
            d = json.loads(line)
            p = d['path']
            if p in survivors and os.path.exists(survivors[p]):
                add(d['hash'], f'old original, library copy {survivors[p]}')
            elif p in video_paths and os.path.exists(video_paths[p]):
                add(d['hash'], f'old original, video copy {video_paths[p]}')
            elif p in deleted:
                add(d['hash'], f'old original {p}, deleted with proof')

    if holdout_grant:
        grant = os.path.join(HHD, 'Photosusa', HOLDOUT)
        if os.path.isdir(grant):
            for p, h in file_hashes(tree_files(grant)).items():
                add(h, f'kept intact outside the library: {p}')
    return known, src


def is_junk(rel):
    b = rel.rsplit('/', 1)[-1]
    return (rel.startswith('__MACOSX/') or b.startswith('._')
            or b in ('.DS_Store', 'Thumbs.db', 'desktop.ini', '.localized',
                     '.AppleDouble') or b.lower().endswith('.aae'))
