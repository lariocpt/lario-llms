#!/usr/bin/env python3
"""One folder per day.


Merges the folders that split a single day — a date echo (`2014-10-08 October 8`)
or a nameless batch (`2014-10-08 Unsorted`) sitting beside a named event — into
one folder per day, keeping a real event name where one exists:

  2014/2014-10-08 October 8   +  2014/2014-10-08 Unsorted   ->  2014/2014-10-08
  2015/2015-01-17 Cape Town, January 17  +  .../Unsorted    ->  2015/2015-01-17 Cape Town, January 17

A label counts as real only if it is not 'Unsorted' and not just the date
spelled out. Names are renumbered sequentially per day after merging, so
collisions cannot happen; files without a capture timestamp keep their original
name and get a -2/-3 suffix on collision. Videos under /mnt/media/videos
follow the identical mapping so photo and video trees stay parallel.
manifest-moves.csv and manifest-videos.csv are rewritten. DRY=1 (default) only
prints the plan.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/consolidate_days.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import os
import re
import shutil
from collections import defaultdict
from calendar import month_name

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import LIB
from paths import VIDLIB as VID
DRY = os.environ.get('DRY', '1') != '0'

KEEP_TOP = {'Undated', 'Misc', '_apps'}
DAY = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(?: (.*))?$')
TS_NAME = re.compile(r'^\d+_(\d{8}-\d{6})$', re.I)


def is_date_echo(label, y, m, d):
    """True if the label carries no information beyond a date.

    Catches the folder's own date and the off-by-one spellings that camera-clock
    and export-tool naming produced ('2015-08-12 August 13'). Anything naming a
    place or event ('Cape Town, October 4', 'San Francisco, May 26') is real.
    """
    if not label:
        return True
    s = label.strip().lower().replace('.', '').replace(',', ' ')
    s = ' '.join(s.split())
    forms = {f'{month_name[int(m)].lower()} {int(d)}', f'{month_name[int(m)].lower()[:3]} {int(d)}',
             f'{y}-{int(m):02d}-{int(d):02d}', f'{y} {month_name[int(m)].lower()} {int(d)}'}
    if s in forms:
        return True
    if re.fullmatch(r'([a-z]{3,9}) (\d{1,2})', s):
        mon, day = s.split()
        names = {month_name[i].lower() for i in range(1, 13)} | {month_name[i].lower()[:3] for i in range(1, 13)}
        return mon in names and 1 <= int(day) <= 31
    return False


def plan():
    """(src_dir -> dst_dir) for photos, derived from the folder column."""
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-moves.csv'), encoding='utf-8')))
    files_by_dir = defaultdict(list)
    for r in rows:
        files_by_dir[r['folder']].append(r['new'])
    by_day = defaultdict(set)
    for folder in files_by_dir:
        parts = folder.split('/')
        if parts[0] in KEEP_TOP or len(parts) != 2:
            continue
        m = DAY.match(parts[1])
        if m:
            by_day[(parts[0], m.group(1), m.group(2), m.group(3))].add(folder)

    mapping = {}
    for (year, y, mo, d), folders in by_day.items():
        day_iso = f'{y}-{mo}-{d}'
        labels = {}
        for f in folders:
            label = DAY.match(f.split('/')[1]).group(4) or ''
            labels.setdefault(label, 0)
            labels[label] += len(files_by_dir[f])
        def is_real(l):
            """A label worth keeping: names something beyond the day itself."""
            return bool(l.strip()) and l.strip().lower() != 'unsorted' \
                and not is_date_echo(l, y, mo, d)

        real = [l for l in labels if is_real(l)]
        if len(real) <= 1:
            chosen = real[0] if real else ''
            for f in folders:
                dst = f'{year}/{day_iso} {chosen}'.rstrip()
                if f != dst:
                    mapping[f] = dst
        else:
            # The day carries two genuinely different events (e.g. "Mountain View,
            # September 17" and "Los Angeles, September 18"). Those folders are left
            # alone; only the nameless batches and bare date echoes join the busiest
            # event, so no real event name is ever discarded.
            primary = max(real, key=lambda l: (labels[l], len(l)))
            target = f'{year}/{day_iso} {primary}'.rstrip()
            for f in folders:
                label = DAY.match(f.split('/')[1]).group(4) or ''
                if label == primary or is_real(label):
                    continue  # another real event: keep its own folder
                mapping[f] = target
    return rows, files_by_dir, mapping


def rename_files(rows, mapping):
    """Return {(old_new_path): (new_new_path)} after renumbering per target dir."""
    by_target = defaultdict(list)
    for r in rows:
        folder = r['folder']
        target = mapping.get(folder, folder)
        by_target[target].append(r)
    renames = {}
    for target, items in by_target.items():
        items.sort(key=lambda r: (r['dt'] or 'zzzz', os.path.basename(r['new'])))
        used = set()
        counter = 0
        for r in items:
            base = os.path.basename(r['new'])
            stem, ext = os.path.splitext(base)
            m = TS_NAME.match(stem)
            if m:
                counter += 1
                cand = f'{counter:03d}_{m.group(1)}{ext.lower()}'
            else:
                cand = base
                k = 1
                while cand.lower() in used:
                    k += 1
                    cand = f'{stem}-{k}{ext}'
            used.add(cand.lower())
            new_path = f'{target}/{cand}'
            if new_path != r['new']:
                renames[r['new']] = new_path
    return renames


def video_mapping(video_rows, mapping, photo_rows):
    """Map video dirs through the same day merge so both trees stay parallel.

    A video folder follows the photo folder of its day: the merged/renamed target
    if there is one, otherwise the day's primary event folder, otherwise (a day
    with no photos at all) its own name with an Unsorted/date-echo label dropped.
    """
    primary = {}   # (year, y, mo, d) -> busiest surviving photo dir that day
    counts = defaultdict(int)
    for r in photo_rows:
        folder = mapping.get(r['folder'], r['folder'])
        parts = folder.split('/')
        if parts[0] in KEEP_TOP or len(parts) != 2:
            continue
        m = DAY.match(parts[1])
        if m:
            key = (parts[0], m.group(1), m.group(2), m.group(3))
            counts[(key, folder)] += 1
            primary[key] = folder
    for (key, folder), n in counts.items():
        best = primary.get(key)
        if n > counts[(key, best)] or (n == counts[(key, best)] and len(folder) > len(best)):
            primary[key] = folder

    surviving = set(counts)
    out = {}
    by_target = defaultdict(list)
    for r in video_rows:
        d = r['dest_dir']
        parts = d.split('/')
        target = mapping.get(d)
        if target is None and len(parts) == 2 and parts[0] not in KEEP_TOP:
            m = DAY.match(parts[1])
            if m:
                key = (parts[0], m.group(1), m.group(2), m.group(3))
                label = (m.group(4) or '').strip()
                if (key, d) in surviving:
                    target = d                      # already the day's event folder
                elif key in primary:
                    target = primary[key]           # join the photos of that day
                elif label.lower() == 'unsorted' or not label or is_date_echo(
                        label, m.group(1), m.group(2), m.group(3)):
                    target = f'{parts[0]}/{m.group(1)}-{m.group(2)}-{m.group(3)}'
        by_target[target or d].append(r)
    for target, items in by_target.items():
        items.sort(key=lambda r: (r['dt'] or 'zzzz', r['dest_name']))
        used = set()
        counter = 0
        for r in items:
            stem, ext = os.path.splitext(r['dest_name'])
            m = TS_NAME.match(stem)
            if m:
                counter += 1
                cand = f'{counter:03d}_{m.group(1)}{ext.lower()}'
            else:
                cand = r['dest_name']
                k = 1
                while cand.lower() in used:
                    k += 1
                    cand = f'{stem}-{k}{ext}'
            used.add(cand.lower())
            new_dest = f'{target}/{cand}'
            if new_dest != r['dest']:
                out[r['dest']] = new_dest
    return out


def move_all(pairs, root):
    """Rename every file in two phases so no move can land on a file that is
    still waiting to move (in-place renumbering makes such chains inevitable)."""
    stage = os.path.join(root, '.reorg-stage')
    os.makedirs(stage, exist_ok=True)
    staged = []
    for i, (old, new) in enumerate(sorted(pairs.items())):
        src = os.path.join(root, old)
        if not os.path.exists(src):
            continue
        dst = os.path.join(root, new)
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        tmp = os.path.join(stage, f'{i:06d}')
        os.rename(src, tmp)
        staged.append((tmp, dst))
    for tmp, dst in staged:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            raise SystemExit(f'refuse to overwrite {dst}')
        os.rename(tmp, dst)
    shutil.rmtree(stage, ignore_errors=True)
    return len(staged)


def main():
    rows, _files_by_dir, mapping = plan()
    renames = rename_files(rows, mapping)
    vrows = list(csv.DictReader(open(os.path.join(W, 'manifest-videos.csv'), encoding='utf-8')))
    vremap = video_mapping(vrows, mapping, rows)

    print(f"{'DRY RUN' if DRY else 'APPLYING'}")
    print(f'directories merged/renamed: {len(mapping)}   photos re-pathed: {len(renames)}')
    print(f'videos re-pathed: {len(vremap)}')
    before = {r['folder'] for r in rows} | {r['dest_dir'] for r in vrows}
    after = {mapping.get(r['folder'], r['folder']) for r in rows} | \
            {os.path.dirname(vremap.get(r['dest'], r['dest'])) for r in vrows}
    print(f'distinct folders: {len(before)} -> {len(after)}')
    for src in sorted(mapping)[:14]:
        print(f'  {src}  ->  {mapping[src]}')
    if len(mapping) > 14:
        print(f'  ... {len(mapping) - 14} more')

    if DRY:
        print('\nrun with DRY=0 to apply')
        return

    applied = move_all(renames, LIB) + move_all(vremap, VID)

    lookup = {r['new']: r for r in rows}
    for old, new in renames.items():
        r = lookup[old]
        r['new'] = new
        r['folder'] = os.path.dirname(new)
    vlook = {r['dest']: r for r in vrows}
    for old, new in vremap.items():
        r = vlook[old]
        r['dest'] = new
        r['dest_dir'] = os.path.dirname(new)
        r['dest_name'] = os.path.basename(new)

    with open(os.path.join(W, 'manifest-moves.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r['new']))
    with open(os.path.join(W, 'manifest-videos.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(vrows[0].keys()), quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(sorted(vrows, key=lambda r: r['dest']))

    pruned = 0
    for root, dirs, _files in os.walk(LIB, topdown=False):
        if not dirs and not os.listdir(root) and root != LIB:
            os.rmdir(root)
            pruned += 1
    print(f'\nmoved {applied} files, pruned {pruned} empty directories')


if __name__ == '__main__':
    main()
