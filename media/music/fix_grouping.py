"""Repair album grouping (§19.14): album-artist backfill and scattered compilations.

Navidrome builds an album from *album artist + album name*. The defect was not that
album artist was missing (it is present on 94.6 % of files, measured with mutagen --
the exiftool census's "7.2 %" read a tag name this host's exiftool does not define, so
it counted an empty column): it was that on 21 797 of them the album artist **is the
track artist repeated**, which splits every album whose tracks name different artists,
and that scattered genuine compilations across one folder per artist -- 80's Night
Ultimate DJ Collection sat as 302 files across 273 artist folders. At the start of this
repair the player's own index held 7 963 albums, 5 560 of them a single track, against
3 419 distinct album strings.

Two rules, both fill-only unless told otherwise:

    compilations   an album string that lives in more than one artist dir and names
                   more than one track artist is a compilation: Album Artist becomes
                   "Various Artists" and the compilation flag is set -- but only when
                   no single artist folder holds more than --max-per-dir of its files.
                   That ceiling is what keeps `Greatest Hits` from becoming one album.
    albumartist    an album string whose files name exactly one artist gets that
                   artist written into Album Artist, so the fallback stops applying.

Nothing moves. Nothing is deleted. Audio bytes are never rewritten: the file is
copied to a temporary in its own directory, the tags are filled into the copy, the
copy is re-read and checked (target tags present, and duration/bitrate/sample-rate/
channels identical to the original), and only then does an atomic replace put it in
place. Before a file is touched at all its original bytes are copied -- verified by
SHA-256 -- to the protect volume, and its previous tag values are appended to
``tag-backup.jsonl``, so ``--undo`` reverses the tags in seconds and the byte-exact
originals survive the run for a full restore.

Default is plan-only. Evidence lives in ``<dest>/_mediatool/<run_id>/``: ``plan.json``
(parameters and counts, immutable), ``actions.jsonl`` (one line per file, the exact
old and new values), ``review-scatter.jsonl`` (the albums the merge will join, so a
wrong merge is visible before anything is written), ``review-shared.jsonl`` (the
groups it refused to join, with the reason), ``tag-backup.jsonl`` (what was written,
so ``--undo`` knows precisely which files it touched), ``verify.json``, ``SUMMARY.txt``.

    python media/.venv/bin/python media/music/fix_grouping.py            # plan
    python media/.venv/bin/python media/music/fix_grouping.py --apply --sample 30
    python media/.venv/bin/python media/music/fix_grouping.py --apply
    python media/.venv/bin/python media/music/fix_grouping.py --undo <run_id>
"""
if __name__ != "__main__":
    raise SystemExit("fix_grouping.py is a command, not a library")

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.dirname(HERE)
for _p in (MEDIA, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import fsx, gate, ledger  # noqa: E402
from paths import LIB  # noqa: E402

try:
    from mutagen import File as MFile          # a function, not a module
    from mutagen.id3 import ID3, TCMP, TPE2    # TPE2 = album artist, TCMP = iTunes flag
    from mutagen.mp4 import MP4Tags
except ImportError:  # pragma: no cover - the gate reports this instead
    MFile = ID3 = MP4Tags = TCMP = TPE2 = None

# Vorbis comments are behind a private class name. If it ever moves, every Vorbis file
# becomes "unsupported container" and is skipped, which is honest; guessing that an
# unknown dict is Vorbis is not.
try:
    from mutagen._vorbis import VCommentDict as VorbisTags
except ImportError:  # pragma: no cover
    VorbisTags = None


def tag_style(tags):
    """Which vocabulary a tag container speaks: 'id3', 'mp4', 'vorbis', or None.

    Keyed on the *container*, not the file handler, because the handler lies about the
    vocabulary: a WAV carries an ID3 chunk (mutagen's `_WaveID3`) and an AIFF carries an
    ID3 chunk too, so dispatching on `type(handle).__name__` reads a real TPE2 as if it
    were a Vorbis comment and writes back garbage. None means this tool will not guess.
    """
    if ID3 is not None and isinstance(tags, ID3):
        return 'id3'
    if MP4Tags is not None and isinstance(tags, MP4Tags):
        return 'mp4'
    if VorbisTags is not None and isinstance(tags, VorbisTags):
        return 'vorbis'
    return None


def _id3_frame(tags, frame_id, text):
    """Set an ID3 text frame by id, built from the class mutagen ships for it.

    TCMP is not an ECMA frame -- it is the iTunes convention Navidrome and dhowden/tag
    read -- but mutagen does register a class for it, so both are constructed from that
    class rather than by asking a container for a frame factory it does not have.
    """
    frame_class = {'TPE2': TPE2, 'TCMP': TCMP}.get(frame_id)
    if frame_class is None:
        raise KeyError(f'this mutagen has no frame class for {frame_id}')
    tags.add(frame_class(encoding=3, text=[text]))      # encoding 3 = UTF-8

# An album string that means "no album". Grouping by one of these would weld
# unrelated releases together, so they are never grouped and never written.
PLACEHOLDER_ALBUMS = frozenset({
    '', 'unknown album', 'album', 'title', 'untitled', 'no title', 'no album',
    'unnamed', 'n/a', 'na', 'none', 'unknown', 'music', 'songs', 'sounds',
})

# The multi-word placeholders, which stay placeholders with anything appended: some tool
# in this library timestamped them ('unknown album 01 27 06 27 53 pm').
PLACEHOLDER_PREFIXES = tuple(p for p in PLACEHOLDER_ALBUMS if ' ' in p)

# Top-level dirs whose name is not an artist identity, so a name there must not
# become anyone's album artist.
UNTRUSTED_TOP = frozenset({'_Unsorted', '_mediatool', 'Unsorted', 'Unassigned'})

VARIOUS_DEFAULT = 'Various Artists'
TMP_INFIX = '.retag-tmp-'
# The same floor the driver uses (§3.2.1): never begin a write run that would leave a
# volume under this much free. Decimal GB, matching FLOOR_GB in run.py.
FLOOR_BYTES = 50 * 1000 * 1000 * 1000


def norm(value):
    """The key an album is grouped by: case, punctuation, years and CD markers out."""
    if not value:
        return ''
    text = unicodedata.normalize('NFKC', str(value)).casefold().replace('\u2019', "'")
    text = re.sub(r'\(?\b(1[89]|20)\d\d\b\)?', ' ', text)
    text = re.sub(r'\b(cd|disc|disk)\s*\.?\s*\d+\b', ' ', text)
    text = re.sub(r'\b(ep|single|remaster(?:ed)?|deluxe|edition|mono|stereo)\b', ' ', text)
    text = re.sub(r'[^0-9a-z\u00c0-\uffff]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def is_placeholder(album_norm):
    """Is this album string a placeholder rather than a name.

    Exact matching was not enough. This library contains `Unknown Album 01 27 06 27 53 pm`
    -- a placeholder some tool timestamped -- and grouping by it would weld Black Keys,
    Blink 182 and Limp Bizkit into one album. A placeholder phrase followed by more words
    is still that placeholder, so any multi-word placeholder used as a prefix counts too.
    """
    if album_norm in PLACEHOLDER_ALBUMS:
        return True
    return any(album_norm.startswith(f'{phrase} ') for phrase in PLACEHOLDER_PREFIXES)


def album_key(value):
    """The album identity a player actually groups on: the string as tagged.

    Deliberately NOT norm(). Stripping years and 'disc 2' groups releases a player would
    never join, and a merge that a player would not perform is not free: writing
    `album artist = Various Artists` on a single artist's album moves it under Various
    Artists and welds it to every other release carrying the same name. `Anthology` in
    this library is one such collision -- A Tribe Called Quest's own album shares the
    string with unrelated files, and the aggressive key proposed to make them one album.
    """
    if value is None:
        return ''
    text = unicodedata.normalize('NFKC', str(value)).casefold()
    return re.sub(r'\s+', ' ', text).strip()


def split_track(value):
    """'14/19' -> (14, 19); '7' -> (7, None)."""
    if value is None:
        return None, None
    text = str(value).strip()
    match = re.match(r'^(\d+)\s*/\s*(\d+)$', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.match(r'^(\d+)$', text)
    if match:
        return int(match.group(1)), None
    return None, None


def _text(values):
    if isinstance(values, (list, tuple)):
        values = values[0] if values else None
    return None if values is None else str(values).strip() or None


def _mp4_bool(value):
    """MP4 booleans come back as a plain bool in 1.48 (and as a list in older releases)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)) and value:
        first = value[0]
        if isinstance(first, (list, tuple)):
            return bool(first[0]) if first else False
        return bool(first)
    return False


def _mp4_pair(value):
    """trkn/disc are ((number, total), ...) -- or absent, or a bool for an unset box."""
    if isinstance(value, (list, tuple)) and value:
        pair = value[0]
        if isinstance(pair, (list, tuple)) and pair:
            number = int(pair[0]) if pair[0] else None
            total = int(pair[1]) if len(pair) > 1 and pair[1] else None
            return number, total
    return None, None


def read_one(path):
    """Tags + audio identity for one file. Never raises: an unreadable file is data."""
    record = {'path': path}
    try:
        stat = os.stat(path)
        record['size'] = stat.st_size
    except OSError as exc:
        record['error'] = f'stat: {exc}'
        return record
    try:
        handle = MFile(path)
    except Exception as exc:  # mutagen raises per-format error types
        record['error'] = f'{type(exc).__name__}: {exc}'
        return record
    if handle is None or handle.tags is None:
        record['error'] = 'no tags readable by mutagen'
        return record
    record['kind'] = type(handle).__name__
    info = getattr(handle, 'info', None)
    if info is not None:
        try:
            record['info'] = {'length': round(float(getattr(info, 'length', 0.0) or 0.0), 2),
                              'bitrate': int(getattr(info, 'bitrate', 0) or 0),
                              'sample_rate': int(getattr(info, 'sample_rate', 0) or 0),
                              'channels': int(getattr(info, 'channels', 0) or 0)}
        except Exception as exc:
            record['info_error'] = str(exc)
    tags = handle.tags
    style = tag_style(tags)
    if style is None:
        record['error'] = f'unsupported tag container {type(tags).__name__}'
        return record
    try:
        if style == 'id3':
            record['album'] = _text(tags.get('TALB'))
            record['title'] = _text(tags.get('TIT2'))
            record['albumartist'] = _text(tags.get('TPE2'))
            record['artist'] = _text(tags.get('TPE1'))
            record['track'], record['tracktotal'] = split_track(_text(tags.get('TRCK')))
            record['compilation'] = 'TCMP' in tags
        elif style == 'mp4':
            record['album'] = _text(tags.get('\u00a9alb'))
            record['title'] = _text(tags.get('\u00a9nam'))
            record['albumartist'] = _text(tags.get('aART'))
            record['artist'] = _text(tags.get('\u00a9ART'))
            record['track'], record['tracktotal'] = _mp4_pair(tags.get('trkn'))
            record['compilation'] = _mp4_bool(tags.get('cpil'))
        else:  # Vorbis comments: FLAC, OGG, Opus, and AIF/WAV carrying them
            record['album'] = _text(tags.get('album'))
            record['title'] = _text(tags.get('title'))
            record['albumartist'] = _text(tags.get('albumartist') or tags.get('album artists'))
            record['artist'] = _text(tags.get('artist'))
            record['track'], record['tracktotal'] = split_track(_text(tags.get('tracknumber')))
            flag = _text(tags.get('compilation'))
            record['compilation'] = bool(flag and flag not in ('0', 'false', 'no'))
    except Exception as exc:
        record['error'] = f'tag read: {type(exc).__name__}: {exc}'
        return record
    return record


def apply_tags(path, wanted):
    """Write `wanted` into `path` (a copy, never the library file) and save.

    `wanted` uses the abstract keys 'albumartist' and 'compilation'; the frame or
    comment each format actually stores is decided here, from what the library's own
    already-tagged files use: TPE2/TCMP for MP3, aART/cpil for MP4, Vorbis comments
    elsewhere. Returns the abstract keys it wrote.
    """
    handle = MFile(path)
    if handle is None or handle.tags is None:
        raise ValueError('no tag container to write into')
    tags, style = handle.tags, tag_style(handle.tags)
    if style is None:
        raise ValueError(f'unsupported tag container {type(handle.tags).__name__}')
    written = set()
    if style == 'id3':
        if 'albumartist' in wanted:
            _id3_frame(tags, 'TPE2', wanted['albumartist'])
            written.add('albumartist')
        if wanted.get('compilation'):
            _id3_frame(tags, 'TCMP', '1')
            written.add('compilation')
    elif style == 'mp4':
        if 'albumartist' in wanted:
            tags['aART'] = [wanted['albumartist']]
            written.add('albumartist')
        if wanted.get('compilation'):
            tags['cpil'] = True
            written.add('compilation')
    else:
        if 'albumartist' in wanted:
            tags['albumartist'] = [wanted['albumartist']]
            written.add('albumartist')
        if wanted.get('compilation'):
            tags['compilation'] = ['1']
            written.add('compilation')
    handle.save()
    return written


def clear_tags(path, keys):
    """Remove the named abstract tags again -- the undo of a value that was absent."""
    handle = MFile(path)
    if handle is None or handle.tags is None:
        raise ValueError('no tag container to clear')
    tags, style = handle.tags, tag_style(handle.tags)
    if style is None:
        raise ValueError(f'unsupported tag container {type(handle.tags).__name__}')
    for key in keys:
        try:
            if style == 'id3':
                tags.delall('TPE2' if key == 'albumartist' else 'TCMP')
            elif style == 'mp4':
                del tags['aART' if key == 'albumartist' else 'cpil']
            else:
                del tags['albumartist' if key == 'albumartist' else 'compilation']
        except KeyError:
            pass                      # already gone -- undo is idempotent
    handle.save()


def protect_original(path, library, root):
    """Copy the untouched bytes to `root`, verified by SHA-256. The only safety net.

    /mnt/xfs is XFS: no snapshots, no copy-on-write, and no second copy of this library
    existed anywhere. The protect volume is the *other* disk, so a power cut mid-run
    costs nothing that a restore cannot undo.
    """
    target = os.path.join(root, os.path.relpath(path, library))
    if os.path.exists(target):
        return {'protected': target, 'skipped': True}
    receipt = fsx.copy_file(path, target, verify=True, digest=None)
    return {'protected': target, 'bytes': receipt['bytes'], 'sha256': receipt['sha256'],
            'skipped': False}


def scan(dest, jobs):
    """Every audio file under `dest`, read concurrently. Errors are kept as records."""
    extensions = gate.extensions_for('music')
    paths = []
    for dirpath, dirnames, filenames in os.walk(dest):
        dirnames[:] = sorted(d for d in dirnames if d not in ('_mediatool', '.git'))
        for name in filenames:
            if os.path.splitext(name)[1].lower() in extensions:
                paths.append(os.path.join(dirpath, name))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        records = list(pool.map(read_one, paths))
    return paths, records


def top_of(dest, path):
    """The artist tier: the first path component below the library root."""
    relative = os.path.relpath(path, dest)
    return relative.split(os.sep, 1)[0] if os.sep in relative else ''


def player_albums(records, dest, decisions):
    """How many albums the player reports, now and after the plan, by Navidrome's rule.

    Every file is counted, including the ones carrying a placeholder album string: the
    player shows those too, as one album per album artist. Excluding them is how a plan
    reported 4 463 albums while the player's own index said 7 940 and its one-track
    count said 5 550 against this function's 4 463.
    """
    def key_for(rec, after):
        album = album_key(rec.get('album'))
        artist = album_key(rec.get('albumartist') or rec.get('artist'))
        if is_placeholder(norm(rec.get('album'))):
            return (artist, album)          # shown, just never merged across artists
        if after:
            action = decisions.get(rec['path'])
            if action and 'albumartist' in action['wanted']:
                return (album_key(action['wanted']['albumartist']), album)
        return (artist, album)

    before = collections.Counter(k for k in (key_for(rec, False) for rec in records) if k)
    after = collections.Counter(k for k in (key_for(rec, True) for rec in records) if k)
    return {'albums_before': len(before), 'albums_after': len(after),
            'one_track_before': sum(1 for c in before.values() if c == 1),
            'one_track_after': sum(1 for c in after.values() if c == 1)}


def decide(dest, records, various, rules, override, max_per_dir):
    """What would change, per file, plus the review list and the honest skip reasons."""
    groups = collections.defaultdict(list)
    skipped = collections.Counter()
    for rec in records:
        if rec.get('error'):
            skipped['unreadable by mutagen'] += 1
            continue
        album_norm = norm(rec.get('album'))
        if not album_norm:
            skipped['no album tag'] += 1
            continue
        if is_placeholder(album_norm):
            skipped['placeholder album name'] += 1
            continue
        if top_of(dest, rec['path']) in UNTRUSTED_TOP:
            skipped['under an untrusted top-level dir'] += 1
            continue
        groups[album_key(rec.get('album'))].append(rec)

    actions, review, shared = {}, [], []
    for album_text, members in groups.items():
        dirs = {os.path.dirname(rec['path']) for rec in members}
        artists = {norm(rec.get('artist')) for rec in members if rec.get('artist')}
        scattered = len(dirs) > 1
        multi_artist = len(artists) > 1
        if scattered and multi_artist:
            # A compilation scattered by a bad import puts one or two files in each artist
            # folder. Separate releases that merely share a name -- `Greatest Hits`, `The
            # Singles` -- fill their folders, so the busiest folder tells the two apart.
            # Getting this wrong is not a missed merge: it writes Various Artists over a
            # real artist's album and welds that album to every stranger with the name.
            busiest = max(collections.Counter(os.path.dirname(rec['path'])
                                              for rec in members).values())
            if busiest > max_per_dir:
                skipped['album string shared by separate releases, not one scattered '
                        'compilation (a folder holds a whole album)'] += len(members)
                shared.append({'album': album_text, 'files': len(members),
                               'dirs': len(dirs), 'artists': len(artists),
                               'busiest_folder_holds': busiest,
                               'sample_dirs': sorted(sorted(dirs))[:6]})
                continue
            rule = 'compilations'
            target = various
        elif not multi_artist and artists:
            rule = 'albumartist'
            modal = collections.Counter(rec['artist'] for rec in members
                                        if rec.get('artist')).most_common(1)[0][0]
            target = modal
        else:
            skipped['several artists inside one folder, not scattered '
                    '-- needs a human call'] += 1
            continue
        if rule not in rules:
            continue
        if scattered and multi_artist:
            review.append({'album': album_text, 'dirs': len(dirs), 'files': len(members),
                           'artists': len(artists),
                           'sample_dirs': sorted(sorted(dirs))[:6]})
        for rec in members:
            wanted, old = {}, {}
            existing = rec.get('albumartist')
            if existing is None:
                wanted['albumartist'] = target
            elif override and rule == 'compilations' and norm(existing) == norm(rec.get('artist')):
                wanted['albumartist'] = target       # it only repeats the track artist
            if rule == 'compilations' and not rec.get('compilation'):
                wanted['compilation'] = True
            if not wanted:
                if (rule == 'compilations' and existing is not None and not override
                        and norm(existing) == norm(rec.get('artist'))):
                    # The value it carries is the track artist repeated back, which is the
                    # thing splitting the album. Calling that "already carries the value"
                    # told the operator this library was finished when it was not.
                    skipped['album artist only repeats the track artist, so the album '
                            'stays split (--override-aa-equals-artist rewrites it)'] += 1
                else:
                    skipped['already carries the value'] += 1
                continue
            actions[rec['path']] = {'path': rec['path'], 'rule': rule, 'album': album_text,
                                    'wanted': wanted, 'old': {
                                        'albumartist': existing,
                                        'compilation': bool(rec.get('compilation'))}}
    return actions, review, shared, skipped, groups


def _fsync_dir(directory):
    handle = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def mismatch(record, wanted, baseline_info):
    """Why the written file is not what was promised, or None if it is."""
    if record.get('error'):
        return f'unreadable after write: {record["error"]}'
    if 'albumartist' in wanted and record.get('albumartist') != wanted['albumartist']:
        return f'album artist reads {record.get("albumartist")!r}, wanted {wanted["albumartist"]!r}'
    if wanted.get('compilation') and not record.get('compilation'):
        return 'compilation flag did not land'
    if baseline_info is not None and record.get('info') != baseline_info:
        return (f'audio identity changed: {baseline_info} -> {record.get("info")} '
                '(duration/bitrate/sample-rate/channels must be untouched by a tag write)')
    return None


def commit_one(action, library, protect_root, run_id, book, backup_handle):
    """Protect, retag, verify, swap, journal. One file, all or nothing.

    The verification runs twice: on the staged copy before the swap, and again on the
    library path after it, because the promise is about the file at that path.
    """
    path = action['path']
    wanted = action['wanted']
    baseline = read_one(path)
    if baseline.get('error'):
        return {'ok': False, 'stage': 'read', 'error': baseline['error']}
    if mismatch(baseline, wanted, baseline.get('info')) is None:
        return {'ok': True, 'already': True}

    protection = protect_original(path, library, protect_root)
    temp = os.path.join(os.path.dirname(path), TMP_INFIX + os.path.basename(path))
    if os.path.exists(temp):
        # A leftover temp is evidence of an interrupted write. Refuse the file rather
        # than guessing which of the two copies the owner wants kept.
        return {'ok': False, 'stage': 'pre-clean', 'error': f'a previous write left {temp}'}

    shutil.copyfile(path, temp, follow_symlinks=False)
    shutil.copystat(path, temp, follow_symlinks=False)
    try:
        apply_tags(temp, wanted)
    except Exception as exc:
        return {'ok': False, 'stage': 'write', 'error': f'{type(exc).__name__}: {exc}',
                'temp': temp, 'protected': protection.get('protected')}
    staged = read_one(temp)
    problem = mismatch(staged, wanted, baseline.get('info'))
    if problem:
        return {'ok': False, 'stage': 'verify-staged', 'error': problem, 'temp': temp,
                'protected': protection.get('protected')}

    os.replace(temp, path)
    _fsync_dir(os.path.dirname(path))

    after = read_one(path)
    problem = mismatch(after, wanted, baseline.get('info'))
    if problem:
        return {'ok': False, 'stage': 'verify-final', 'error': problem,
                'protected': protection.get('protected')}

    backup_handle.write(json.dumps({'run_id': run_id, 'path': path, 'old': action['old'],
                                    'new': wanted}, ensure_ascii=False) + '\n')
    backup_handle.flush()
    os.fsync(backup_handle.fileno())
    book.record(run_id, 'tag', src=path, dst=path, bytes=baseline.get('size', 0),
                requested_by='music/fix_grouping.py')
    return {'ok': True, 'protected': protection.get('protected'),
            'protected_bytes': protection.get('bytes', 0), 'size': baseline.get('size', 0)}


def stratify(actions, count):
    """Pick `count` files spread across both rules and every format in the plan."""
    buckets = {}
    for action in sorted(actions, key=lambda a: a['path']):
        key = (action['rule'], os.path.splitext(action['path'])[1].lower())
        buckets.setdefault(key, []).append(action)
    queues = [queue for _, queue in sorted(buckets.items(), key=lambda kv: -len(kv[1]))]
    picked = []
    while len(picked) < count and any(queues):
        for queue in queues:
            if queue and len(picked) < count:
                picked.append(queue.pop(0))
    return picked


def restore_one(path, old, library, protect_root):
    """Put one file's tag values back exactly as they were."""
    wanted, clearing = {}, []
    if old.get('albumartist') is None:
        clearing.append('albumartist')
    else:
        wanted['albumartist'] = old['albumartist']
    if old.get('compilation'):
        wanted['compilation'] = True
    else:
        clearing.append('compilation')
    baseline = read_one(path)
    if baseline.get('error'):
        return {'ok': False, 'error': baseline['error']}
    protection = protect_original(path, library, protect_root)
    temp = os.path.join(os.path.dirname(path), TMP_INFIX + os.path.basename(path))
    if os.path.exists(temp):
        return {'ok': False, 'error': f'a previous write left {temp}'}
    shutil.copyfile(path, temp, follow_symlinks=False)
    shutil.copystat(path, temp, follow_symlinks=False)
    try:
        if wanted:
            apply_tags(temp, wanted)
        if clearing:
            clear_tags(temp, clearing)
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'temp': temp}
    back = read_one(temp)
    problem = mismatch(back, wanted, baseline.get('info'))
    if problem is None and old.get('albumartist') is None and back.get('albumartist') is not None:
        problem = f'album artist should be gone, reads {back.get("albumartist")!r}'
    if problem is None and not old.get('compilation') and back.get('compilation'):
        problem = 'compilation flag should be gone'
    if problem:
        return {'ok': False, 'error': problem, 'temp': temp}
    os.replace(temp, path)
    _fsync_dir(os.path.dirname(path))
    return {'ok': True, 'protected': protection.get('protected')}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='fix_grouping.py', description=__doc__.strip().splitlines()[0],
        epilog='Plan-only unless --apply. Nothing here moves or deletes a file.')
    parser.add_argument('--dest', default=None, help='library to repair (default: the music library)')
    parser.add_argument('--apply', action='store_true', help='write tags; without this, only plan')
    parser.add_argument('--sample', type=int, default=0, help='apply to N files, spread over rules and formats')
    parser.add_argument('--limit', type=int, default=0, help='cap the number of files written')
    parser.add_argument('--undo', metavar='RUN_ID', help='restore the tag values a run changed, then exit')
    parser.add_argument('--protect-parent', default='/mnt/media/_repair-originals',
                        help='where original bytes are copied before a file is touched')
    parser.add_argument('--no-protect', action='store_true',
                        help='skip the safety copy; refused unless --i-accept-no-backup is also given')
    parser.add_argument('--i-accept-no-backup', action='store_true')
    parser.add_argument('--various-artists', default=VARIOUS_DEFAULT)
    parser.add_argument('--rules', default='compilations,albumartist',
                        help='compilations, albumartist, or both')
    parser.add_argument('--override-aa-equals-artist', action='store_true',
                        help='on scattered compilations, replace an album artist that merely repeats the track artist')
    parser.add_argument('--max-per-dir', type=int, default=2, metavar='N',
                        help='an album string counts as ONE scattered compilation only if no artist '
                             'folder holds more than N of its files (default 2). Higher numbers merge '
                             'separate releases that merely share a name -- Greatest Hits, The Singles')
    parser.add_argument('--jobs', type=int, default=8, help='parallel tag readers')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    missing = gate.missing_dependencies('music')
    if missing:
        raise SystemExit('refused: ' + '; '.join(missing))
    if MFile is None:
        # mutagen imported but mutagen.File did not, which is what turned 29 025 files
        # into "unreadable" in zero seconds. A gate that reports success while its
        # reader is None is worse than no gate.
        raise SystemExit('refused: this interpreter has mutagen but not mutagen.File. '
                         'Run as media/.venv/bin/python, or install python-mutagen')
    dest = os.path.realpath(args.dest or gate.dest_for('music'))
    if not os.path.isdir(dest):
        raise SystemExit(f'refused: {dest} is not a directory')
    if args.undo:
        return do_undo(dest, args)

    rules = {item.strip() for item in args.rules.split(',') if item.strip()}
    unknown = rules - {'compilations', 'albumartist'}
    if unknown:
        raise SystemExit(f'refused: unknown rule(s) {", ".join(sorted(unknown))}; '
                         'choose compilations and/or albumartist')
    if args.no_protect and not args.i_accept_no_backup:
        raise SystemExit('refused: --no-protect also needs --i-accept-no-backup, because this '
                         'library has no snapshot and no second copy')

    started = time.time()
    run_id, run_dir = gate.claim_run_dir(dest, 'music', 'retag')
    paths, records = scan(dest, args.jobs)
    actions, review, shared, skipped, _groups = decide(
        dest, records, args.various_artists, rules, args.override_aa_equals_artist,
        args.max_per_dir)
    view = player_albums(records, dest, actions)

    action_path = os.path.join(run_dir, 'actions.jsonl')
    with open(action_path, 'w', encoding='utf-8') as handle:
        for path in sorted(actions):
            handle.write(json.dumps(actions[path], ensure_ascii=False) + '\n')
    review_path = os.path.join(run_dir, 'review-scatter.jsonl')
    with open(review_path, 'w', encoding='utf-8') as handle:
        for row in sorted(review, key=lambda r: (-r['dirs'], r['album'])):
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    # The groups it deliberately did NOT merge, written down rather than hidden in a
    # counter: these share an album string but one folder holds a whole album, so they
    # are separate releases and merging them would be the damage, not the repair.
    shared_path = os.path.join(run_dir, 'review-shared.jsonl')
    with open(shared_path, 'w', encoding='utf-8') as handle:
        for row in sorted(shared, key=lambda r: -r['files']):
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    errors = collections.Counter(rec['error'].split(':')[0] for rec in records if rec.get('error'))
    plan = {
        'run_id': run_id, 'library': dest, 'rules': sorted(rules),
        'various_artists': args.various_artists,
        'override_aa_equals_artist': args.override_aa_equals_artist,
        'max_per_dir': args.max_per_dir,
        'albums_shared_not_merged': len(shared),
        'protect': None if args.no_protect else os.path.join(args.protect_parent, run_id),
        'files_seen': len(paths), 'files_readable': sum(1 for r in records if not r.get('error')),
        'files_to_write': len(actions),
        'by_rule': dict(collections.Counter(a['rule'] for a in actions.values())),
        'player': view, 'skipped': dict(skipped.most_common()),
        'read_errors': dict(errors.most_common(12)),
        'actions_sha256': hashlib.sha256(
            open(action_path, 'rb').read()).hexdigest(),
        'scattered_albums_reviewed': len(review),
    }
    ledger.write_plan(run_dir, plan)

    lines = [f'run            {run_id}',
             f'library        {dest}',
             f'evidence       {run_dir}',
             f'files scanned  {len(paths)} '
             f'({sum(1 for r in records if not r.get("error"))} readable by mutagen)',
             f'albums a player shows now   {view["albums_before"]}, '
             f'{view["one_track_before"]} of them a single track',
             f'albums after this plan      {view["albums_after"]}, '
             f'{view["one_track_after"]} of them a single track',
             f'files to write {len(actions)}  '
             + '  '.join(f'{rule}={count}' for rule, count in sorted(plan['by_rule'].items())),
             '']
    lines.append('not changed, and why:')
    for reason, count in skipped.most_common():
        lines.append(f'  {count:6}  {reason}')
    if errors:
        lines.append('')
        lines.append('files mutagen could not read (left exactly as they are):')
        for kind, count in errors.most_common(8):
            lines.append(f'  {count:6}  {kind}')
    lines += ['', f'the albums this merges, biggest first: {review_path}',
              f'every per-file decision:                 {action_path}']
    if shared:
        lines.append(f'NOT merged, same name different release:   {shared_path} '
                     f'({len(shared)} albums)')
    summary = '\n'.join(lines)
    with open(os.path.join(run_dir, 'SUMMARY.txt'), 'w', encoding='utf-8') as handle:
        handle.write(summary + '\n')
    print(summary)
    print(f'\nelapsed {time.time() - started:.0f}s')

    if not args.apply:
        print('\n# plan only -- nothing was written. Review, then re-run with '
              '--apply --sample 30, then --apply.')
        return 0
    return do_apply(dest, run_id, run_dir, actions, args)


def do_apply(dest, run_id, run_dir, actions, args):
    """Write the plan. Protection first, then one verified file at a time."""
    if args.sample:
        selected = [action['path'] for action in stratify(list(actions.values()), args.sample)]
    else:
        selected = sorted(actions)
    if args.limit:
        selected = selected[:args.limit]
    if not selected:
        print('\n# nothing to write')
        return 0

    protect_root = None
    if not args.no_protect:
        protect_root = os.path.join(args.protect_parent, run_id)
        os.makedirs(protect_root, exist_ok=True)
        needed = sum(os.path.getsize(path) for path in selected if os.path.exists(path))
        free_there = gate.check_floor(protect_root, needed, FLOOR_BYTES)
        gate.check_floor(dest, 0, FLOOR_BYTES)
        print(f'protecting {len(selected)} originals -- {needed / 1e9:.1f} GB onto {protect_root} '
              f'({free_there / 1e9:.1f} GB free there)')
    else:
        print('NO PROTECTION COPY -- originals are not being kept anywhere')

    book = ledger.Ledger(dest, apply=True)
    book.start_run(run_id, 'music', 'retag', 'fix_grouping', [dest], dest,
                   {'rules': args.rules, 'sample': args.sample, 'limit': args.limit,
                    'protect': protect_root})
    written = already = failed = 0
    failures = []
    started = time.time()
    with open(os.path.join(run_dir, 'tag-backup.jsonl'), 'a', encoding='utf-8') as backup:
        for index, path in enumerate(selected, 1):
            try:
                result = commit_one(actions[path], dest, protect_root, run_id, book, backup)
            except Exception as exc:                       # one bad file must not stop the run
                result = {'ok': False, 'stage': 'exception', 'error': f'{type(exc).__name__}: {exc}'}
            if result.get('ok'):
                already += 1 if result.get('already') else 0
                written += 0 if result.get('already') else 1
            else:
                failed += 1
                failures.append(dict(result, path=path))
            if index % 500 == 0:
                print(f'  {index}/{len(selected)}  written={written} already={already} '
                      f'failed={failed}  {time.time() - started:.0f}s', flush=True)
    book.finish_run(run_id, 'done', {'written': written, 'already': already, 'failed': failed})

    lines = ['', '-- applied --',
             f'tags written   {written}   already correct {already}   refused/failed {failed}',
             f'protect copy   {protect_root or "NONE"}',
             f'undo with      --undo {run_id}   (tag values; originals are in the protect copy)',
             f'elapsed        {time.time() - started:.0f}s']
    if failures:
        detail = os.path.join(run_dir, 'failures.jsonl')
        with open(detail, 'w', encoding='utf-8') as handle:
            for row in failures:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        lines.append(f'failures       {detail} ({len(failures)} lines)')
        for row in failures[:8]:
            lines.append(f'  {row.get("stage")}: {row["path"]} -- {row["error"]}')
    lines.append('')
    lines.append('Navidrome will not notice until it rescans: in the web UI use Settings -> '
                 'Rescan library, or `docker exec navidrome sh -c "kill -HUP 1"`.')
    report = '\n'.join(lines)
    with open(os.path.join(run_dir, 'APPLY.txt'), 'w', encoding='utf-8') as handle:
        handle.write(report + '\n')
    print(report)
    return 0 if not failed else 1


def do_undo(dest, args):
    """Put every tag value back exactly as the named run found it."""
    source = gate.evidence_dir(dest, args.undo)
    backup = os.path.join(source, 'tag-backup.jsonl')
    if not os.path.exists(backup):
        raise SystemExit(f'refused: no tag backup for run {args.undo} at {backup}')
    with open(backup, encoding='utf-8') as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    undo_id, undo_dir = gate.claim_run_dir(dest, 'music', 'undo')
    protect_root = None if (args.no_protect and args.i_accept_no_backup) \
        else os.path.join(args.protect_parent, undo_id)
    if protect_root:
        os.makedirs(protect_root, exist_ok=True)
    print(f'# undo of {args.undo}: {len(lines)} files, run {undo_id}, evidence {undo_dir}')
    restored = failed = 0
    failures = []
    journal_path = os.path.join(undo_dir, 'actions.jsonl')
    journal = open(journal_path, 'w', encoding='utf-8')
    for line in reversed(lines):
        try:
            result = restore_one(line['path'], line['old'], dest, protect_root)
        except Exception as exc:
            result = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        if result.get('ok'):
            restored += 1
        else:
            failed += 1
            failures.append(dict(result, path=line['path']))
        # Journal every restore, not only the failures: without it an undo leaves an empty
        # evidence dir, and nothing on disk says what the library was put back to.
        journal.write(json.dumps({'path': line['path'], 'restored_to': line.get('old'),
                                  'had_been': line.get('new'), 'ok': bool(result.get('ok'))},
                                 ensure_ascii=False) + '\n')
        if (restored + failed) % 500 == 0:
            print(f'  {restored + failed}/{len(lines)} restored={restored} failed={failed}',
                  flush=True)
    journal.close()
    with open(os.path.join(undo_dir, 'SUMMARY.txt'), 'w', encoding='utf-8') as handle:
        handle.write(f'undo of {args.undo}\nfiles {len(lines)}  restored {restored}  '
                     f'failed {failed}\njournal {journal_path}\n')
    print(f'\nrestored {restored}, failed {failed}. Current bytes were copied to {protect_root}.')
    if failures:
        detail = os.path.join(undo_dir, 'failures.jsonl')
        with open(detail, 'w', encoding='utf-8') as handle:
            for row in failures:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(f'failures: {detail}')
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
