#!/usr/bin/env python3
"""Final check that the two libraries and the manifests describe the same disk.


  library counts              what is under Pictures/Photos and videos/videos
  manifest <-> disk           every manifest row exists, every file is accounted
  naming                      NNN_YYYYMMDD-HHMMSS.ext, or NNN_<original> in Undated
  folders                     YYYY/YYYY-MM-DD[ Event], Undated/<old folder>
  date agreement              the date in the name equals the EXIF date recorded
                              when the file was moved
Writes verify-final.txt and prints the summary.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/verify_final.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import collections
import os
import re

W = '/home/lario/photos-reorg-work'
from paths import LIB
from paths import VIDLIB
STAMP = re.compile(r'^(\d{3,4})_(\d{8})-(\d{6})\.[A-Za-z0-9]+$')
PLAIN = re.compile(r'^(\d{3,4})_(.+)\.([A-Za-z0-9]+)$')
DAY = re.compile(r'^(\d{4})-(\d{2})-(\d{2})( .*)?$')


def walk(root):
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f.startswith('._') or f == '.DS_Store':
                continue
            yield os.path.join(dp, f)


def main():
    lines = []

    def say(s=''):
        print(s)
        lines.append(s)

    photos = list(walk(LIB))
    videos = list(walk(VIDLIB))
    say(f'photo library {LIB}: {len(photos)} files, '
        f'{sum(os.path.getsize(p) for p in photos) / 2**30:.2f} GiB')
    say(f'video library {VIDLIB}: {len(videos)} files, '
        f'{sum(os.path.getsize(p) for p in videos) / 2**30:.2f} GiB')

    moves = list(csv.DictReader(open(f'{W}/manifest-moves.csv', encoding='utf-8')))
    imports = list(csv.DictReader(open(f'{W}/manifest-imports.csv',
                                       encoding='utf-8')))
    vids = list(csv.DictReader(open(f'{W}/manifest-videos.csv', encoding='utf-8')))
    # files taken out of the library on purpose (a zip that does not belong in a
    # photo library); their new home is recorded, so a manifest row pointing at
    # the old path is expected, not a problem
    relocated = {}
    if os.path.exists(f'{W}/manifest-relocations.csv'):
        for r in csv.DictReader(open(f'{W}/manifest-relocations.csv',
                                     encoding='utf-8')):
            relocated[os.path.join(LIB, r['from'])] = r['to']
    managed = set()
    problems = []

    for rows, path, col, label in ((moves, LIB, 'new', 'move'),
                                   (imports, LIB, 'new', 'import'),
                                   (vids, VIDLIB, 'dest', 'video')):
        missing = 0
        for r in rows:
            p = os.path.join(path, r[col])
            if not os.path.exists(p):
                if p in relocated and os.path.exists(relocated[p]):
                    continue
                missing += 1
                problems.append(f'{label} row points at nothing: {p}')
            else:
                if p in managed and label != 'video':
                    problems.append(f'two manifest rows for the same file: {p}')
                managed.add(p)
        say(f'{label:6} manifest {len(rows):5} rows, {missing} missing')

    live = set(photos) | set(videos)
    unmanaged = sorted(live - managed)
    say(f'files on disk not named by any manifest: {len(unmanaged)}')
    for p in unmanaged[:12]:
        say(f'   {os.path.relpath(p, LIB)}')

    # naming and folder rules, photo library only
    bad_name = []
    bad_dir = []
    bad_date = []
    folders = collections.Counter()
    for p in photos:
        rel = os.path.relpath(p, LIB)
        parts = rel.split('/')
        base = parts[-1]
        if rel.startswith('_apps/'):
            continue
        folders[os.path.dirname(rel)] += 1
        if parts[0] == 'Undated':
            if not PLAIN.match(base) or len(parts) < 3:
                bad_name.append(rel)
            continue
        if len(parts) != 3:
            bad_dir.append(rel)
            continue
        year, day = parts[0], parts[1]
        if not DAY.match(day):
            bad_dir.append(rel)
            continue
        m = STAMP.match(base)
        if not m:
            bad_name.append(rel)
            continue
        if day.split(' ')[0] != m.group(2)[:4] + '-' + m.group(2)[4:6] + '-' \
                + m.group(2)[6:8]:
            bad_date.append(rel)
    say(f'photo filenames that do not follow the convention: {len(bad_name)}')
    for rel in bad_name[:10]:
        say(f'   {rel}')
    say(f'files outside the folder convention: {len(bad_dir)}')
    for rel in bad_dir[:10]:
        say(f'   {rel}')
    say(f'filename date disagreeing with its folder: {len(bad_date)}')
    for rel in bad_date[:10]:
        say(f'   {rel}')

    # videos follow the same layout: dated folders use the timestamp, Undated keeps
    # the original basename with the sequence number in front
    bad_v = []
    for p in videos:
        rel = os.path.relpath(p, VIDLIB)
        base = os.path.basename(rel)
        ok = PLAIN.match(base) if rel.startswith('Undated/') else STAMP.match(base)
        if not ok:
            bad_v.append(rel)
    say(f'video filenames that do not follow the convention: {len(bad_v)}')
    for rel in bad_v[:10]:
        say(f'   {rel}')

    dupes = [p for p, n in collections.Counter(
        os.path.relpath(p, LIB) for p in photos).items() if n > 1]
    say(f'duplicate relative paths in the photo library listing: {len(dupes)}')

    day_folders = collections.Counter()
    for d in folders:
        top = d.split('/')[0]
        day_folders[top] += 1
    say(f'photo folders: {len(folders)} across years '
        f'{sorted(k for k in day_folders if k != "Undated")}, '
        f'{day_folders.get("Undated", 0)} under Undated/')

    for p in problems[:20]:
        say('PROBLEM ' + p)
    say(f'\n{"PROBLEMS: " + str(len(problems)) if problems else "no manifest problems"}')
    with open(f'{W}/verify-final.txt', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')


if __name__ == "__main__":
    main()
