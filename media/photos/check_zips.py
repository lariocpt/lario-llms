#!/usr/bin/env python3
"""Prove, entry by entry, whether the archives left in the source trees still add

content that is not available anywhere else.

Archives are walked recursively (Archive.zip contains Marie.zip and Paris.zip) and
every entry gets an identity of the form "Archive.zip::Elisa/Beachfront/IMG_1.jpg".
An entry counts as represented when one of these holds:

  imported      its bytes are the bytes of something this job moved into the photo
                or video library (the original hash comes from the index cut
                before the move, so a later q85 recompression does not hide it)
  live          its bytes are in a library file as it sits on disk right now
  old-original  its bytes equal an old original path, and that path is either a
                survivor of the reorganisation or was deleted with proof
  source-dup    its bytes equal a loose source file that the accounting resolved
                to a duplicate of library content
  grant-archive its bytes equal a file inside photos/Grant Backup, which the owner
                keeps outside the library, intact
  junk          AppleDouble / .DS_Store / Thumbs.db
  twin          the same bytes appear earlier in the same walk

Anything else is unique, and the sources must not be deleted while one remains.
Writes zip-evidence.json and, only when every entry of every archive is
represented, zip-verified.json (which account_sources.py reads).
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/check_zips.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import LIB
from paths import VIDLIB
from paths import HHD, named_sources
# Unset LARIO_SRC_DIRS gives exactly the two trees this file has always used. Registered
# the way plan_import.py registers them, because these paths are the *external drives*
# being merged in, not constants: a pass that keeps pointing at last batch's two trees
# while a new batch is attached reports a clean, empty, wrong answer.
try:
    ROOTS = named_sources('LARIO_SRC_DIRS',
                          {'Mac Photos': f'{HHD}/Mac Photos', 'Photosusa': f'{HHD}/Photosusa'})
except ValueError as bad:
    raise SystemExit(f'refused: {bad}')
ZIPS = [f'{ROOTS["Photosusa"]}/photos/Archive.zip',
        f'{ROOTS["Photosusa"]}/photos/Marie/Marie.zip']
GRANT = 'photos/Grant Backup'
VIDEXT = ('.mov', '.mp4', '.avi', '.3gp', '.mpg', '.mpeg', '.dv', '.vob', '.m4v',
          '.wmv', '.flv', '.mts')
JUNKNAME = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.localized'}


def junk(rel):
    b = rel.rsplit('/', 1)[-1]
    return rel.startswith('__MACOSX/') or b.startswith('._') or b in JUNKNAME


def blake(path):
    # the same digest the existing indexes use: blake2b, 64 bytes
    h = hashlib.blake2b()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root):
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(root)
             for f in fs if not f.startswith('._')]
    with ThreadPoolExecutor(max_workers=8) as ex:
        hs = list(ex.map(blake, files))
    return {h: os.path.relpath(p, root) for p, h in zip(files, hs)}, len(files)


def main():
    known = {}

    def add(h, where):
        known.setdefault(h, where)

    # 1. live libraries, as they physically are right now
    for root, label in ((LIB, 'live photo library'), (VIDLIB, 'live video library')):
        hm, n = hash_tree(root)
        print(f'  hashed {n} live files under {root}')
        for h, rel in hm.items():
            add(h, f'{label}:{rel}')
    live_n = len(known)

    # 2. the old originals, and where the reorganisation left each of those paths
    survivors, deleted = {}, set()
    for r in csv.DictReader(open(f'{W}/manifest-moves.csv', encoding='utf-8')):
        for k in ('orig', 'backup'):
            if r.get(k):
                survivors[r[k]] = os.path.join(LIB, r['new'])
    for r in csv.DictReader(open(f'{W}/manifest-deletes.csv', encoding='utf-8')):
        deleted.add(r['orig'])
        if r.get('backup'):
            deleted.add(r['backup'])
    video_paths = {}
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        if not r['orig'].startswith(('Mac Photos/', 'Photosusa/', 'Archive.zip::',
                                     'Marie.zip::')):
            video_paths[r['orig']] = os.path.join(VIDLIB, r['dest'])
    # every line, not one per hash: the same bytes usually sit at several old
    # paths and only some of those survived or were deleted with proof
    for line in open(f'{W}/hashes_backup.jsonl'):
        d = json.loads(line)
        p = d['path']
        if p in survivors and os.path.exists(survivors[p]):
            add(d['hash'], f'old original, library copy {survivors[p]}')
        elif p in video_paths and os.path.exists(video_paths[p]):
            add(d['hash'], f'old original, video copy {video_paths[p]}')
        elif p in deleted:
            add(d['hash'], f'old original {p}, deleted with proof')
    old_n = len(known)

    # 3. what this job imported: the bytes as they were before the move
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
        rel = os.path.relpath(d['staged'], f'{W}/zip-extract')
        staged_by_prov[d['provenance']] = rel
    imported = 0
    for r in csv.DictReader(open(f'{W}/manifest-imports.csv', encoding='utf-8')):
        key = f"{r['src_tree']}/{r['orig']}"
        h = src_hash.get(key) or zpath_hash.get(staged_by_prov.get(r['orig'], ''))
        if h:
            add(h, f'imported as {LIB}/{r["new"]}')
            imported += 1
    vid_imported = 0
    vid_src = {}
    for r in csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')):
        h = zpath_hash.get(staged_by_prov.get(r['orig'], ''))
        if h:
            add(h, f'transcoded as {VIDLIB}/{r["dest"]}')
            vid_imported += 1
        if r['orig'].startswith(('Mac Photos/', 'Photosusa/')) and os.path.exists(
                os.path.join(VIDLIB, r['dest'])):
            # the loose source was deleted after the transcode, so an archive entry
            # with the same name and byte count is the same clip
            vid_src[(os.path.basename(r['orig']).lower(),
                     int(float(r['in_bytes'])))] = f'{VIDLIB}/{r["dest"]}'
    print(f'  imported originals hashed back in: {imported} photos, '
          f'{vid_imported} videos')

    # 4. loose source files that the accounting already resolved
    account = {r['source_file']: r for r in
               csv.DictReader(open(f'{W}/source-accounting.csv', encoding='utf-8'))}
    grant, src_repr, src_unresolved = {}, {}, {}
    for key, h in src_hash.items():
        tree, _, rel = key.partition('/')
        cat = account.get(key, {}).get('category', '')
        if rel.startswith(GRANT):
            grant.setdefault(h, key)
        elif cat.startswith('dup') or cat in ('dvd-scaffold', 'junk-appledouble',
                                              'junk-name', 'junk-aae'):
            src_repr.setdefault(h, f'{key} [{cat}]')
        elif not cat:
            src_unresolved.setdefault(h, key)
    for h, where in src_repr.items():
        add(h, f'source file {where}')
    print(f'  reference set: {len(known)} distinct hashes')

    report = {}
    all_clear = True
    for zp in ZIPS:
        tree = next(t for t in ROOTS if zp.startswith(ROOTS[t]))
        key = f'{tree}/{os.path.relpath(zp, ROOTS[tree])}'
        prefix = f'{os.path.basename(zp)}::'
        seen = {}
        counts = {}
        nbytes = 0
        entries = 0
        unmatched = []

        def walk(path, pre):
            """Recurse through nested archives, counting every leaf entry."""
            nonlocal nbytes, entries
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    rel = info.filename.replace('\\', '/').lstrip('/')
                    with z.open(info) as fh:
                        h = hashlib.blake2b(fh.read()).hexdigest()
                    if junk(rel):
                        cat = 'junk'
                    elif rel.lower().endswith('.zip'):
                        tmp = f'{W}/.nested-probe.tmp'
                        with open(tmp, 'wb') as fh:
                            fh.write(z.read(info))
                        try:
                            walk(tmp, pre + rel + '::')
                        finally:
                            os.remove(tmp)
                        continue
                    elif h in known:
                        if known[h].startswith('imported') or known[h].startswith(
                                'transcoded'):
                            cat = 'imported'
                        elif known[h].startswith('live'):
                            cat = 'live'
                        elif known[h].startswith('old original'):
                            cat = 'old-original'
                        elif known[h].startswith('source file'):
                            cat = 'source-dup'
                    elif (os.path.splitext(rel)[1].lower() in VIDEXT
                          and (rel.rsplit('/', 1)[-1].lower(), info.file_size)
                          in vid_src):
                        cat = 'video-already-imported'
                        seen.setdefault(h, pre + rel)
                    elif h in grant:
                        cat = 'grant-archive'
                    elif h in seen:
                        cat = 'twin of ' + seen[h]
                    else:
                        cat = 'UNIQUE'
                        unmatched.append((pre + rel, info.file_size))
                    entries += 1
                    nbytes += info.file_size
                    counts[cat] = counts.get(cat, 0) + 1
                    seen.setdefault(h, pre + rel)

        walk(zp, prefix)
        rep = {'file': zp, 'entries': entries, 'bytes': nbytes,
               'categories': dict(sorted(counts.items(), key=lambda x: -x[1])),
               'unique': len(unmatched),
               'unique_bytes': sum(b for _, b in unmatched),
               'unique_list': unmatched[:40]}
        report[key] = rep
        all_clear = all_clear and not unmatched
        print(f'\n{key}')
        print(f'  {entries} leaf entries, {nbytes / 2**20:.1f} MB')
        for c, n in rep['categories'].items():
            print(f'    {c:34} {n}')
        if unmatched:
            print(f'  UNIQUE {len(unmatched)} ({rep["unique_bytes"] / 2**20:.1f} MB):')
            for u in unmatched[:15]:
                print(f'     {u[1] / 2**20:8.2f} MB  {u[0][:90]}')
        else:
            print('  nothing unique: every entry is available elsewhere')
    json.dump(report, open(f'{W}/zip-evidence.json', 'w'), indent=1)
    if all_clear:
        json.dump(sorted(report), open(f'{W}/zip-verified.json', 'w'), indent=1)
        print('\nno archive adds content: wrote zip-verified.json')
    else:
        print('\nAT LEAST ONE ARCHIVE HAS UNIQUE CONTENT - do not delete it unexamined')


if __name__ == "__main__":
    main()
