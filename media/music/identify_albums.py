"""Fill the album tag where it is missing but the title is known (§19.14, §17 Open 5).

3 155 files in this library carry no album tag, so the player shows them one per song
under ``[Unknown Album]``. Read properly -- not through exiftool, which on this host has
no ``AlbumArtist`` name at all, and not through a reader that never returned a title --
**3 134 of them do carry a title**, which makes this a lookup question and not a
fingerprinting one. AcoustID stays unused except for the last twenty files.

Three routes, all **fill-only**: an album is written where the tag is absent or a
placeholder, never over an album that already names something. Every route that can answer
without the network is asked, so the report says what each is worth; two routes naming
*different* albums is refused, because that is two winners and not a tie to break.

    twins   (default) the library already holds this recording -- same title, an artist
            that agrees, duration within ``--tolerance`` -- and every twin that qualifies
            names one and the same album. Offline, free, and the only route measured good
            enough to trust with a library this age.
    folder  (default) at least TWO tagged files in the folder this file is standing in name
            one album, and the folder is not bigger than that album already is. Answers
            whole albums twins cannot -- unique tracks whose only evidence is that they sit
            together -- but **applied once and undone**: ``Artist/[Unknown Album]/`` is a
            junk drawer, not an album folder, and with one tagged file as evidence it welded
            45 Canibus files onto ``Rip The Jacker``. The two guards cut it from 372 writes
            to 58; the folder route refuses anything it cannot state safely.
    musicbrainz  (opt-in, ``--routes twins,folder,musicbrainz``) WS/2 recording search.
            **Measured on this library and off by default: 4 fills in 60 lookups, and the
            fills were wrong.** Searching ``Thunderstruck / AC-DC`` returns no studio
            album at all -- only ``Stiff in Milwaukee``, ``All My Friends Are Gonna Be
            There Too``, ``Live at River Plate`` -- all type=Album, all durations matching,
            because a bootleg ripped off the same CD has the same length. ``Heaven Ain't
            Hard To Find`` answers ``Live It Up``, a 241 s recording; the real 2Pac track
            is 275 s. The duration test cannot separate a bootleg from a real release when
            they share a master, so do not run this route hoping for a better rate: the
            client stays because a release-group search with artist MBIDs would be worth
            writing, not because this query is.

The rule throughout is *single winner or leave it*, because a wrong album is invisible
while ``[Unknown Album]`` is at least honest.

Nothing moves and nothing is deleted. Audio bytes are never rewritten: the file is copied
to a temporary in its own directory, the album is filled into the copy, the copy is
re-read and checked, and only then ``os.replace`` swaps it in. Before a file is touched
its untouched bytes go to ``--protect-parent`` on the *other* disk, verified by SHA-256 --
``/mnt/xfs`` is XFS, with no snapshots and no copy-on-write, and this library has no
second copy. ``--undo`` puts album values back from ``tag-backup.jsonl``, which records
what was written rather than what was planned.

Evidence, per §4.3.4, under ``<dest>/_mediatool/<run_id>/``: ``plan.json``,
``decisions.jsonl`` (every candidate, filled or refused, with the candidates that decided
it), ``actions.jsonl``, ``tag-backup.jsonl``, ``SUMMARY.txt``, ``APPLY.txt``. Refusals are
a result, not a gap: they are in ``decisions.jsonl`` with a reason.

    media/.venv/bin/python music/identify_albums.py                 # plan only, no writes
    media/.venv/bin/python music/identify_albums.py --limit 60      # pilot the lookups
    media/.venv/bin/python music/identify_albums.py --apply --sample 30
    media/.venv/bin/python music/identify_albums.py --apply
    media/.venv/bin/python music/identify_albums.py --undo RUN_ID

Plan-only unless ``--apply``, and offline unless ``musicbrainz`` is named in ``--routes``.
Network calls are throttled to one per second, which is what the service asks for, so
opting into that route over 3 240 files costs about an hour of the machine's time.
"""

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
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.dirname(HERE)
for _p in (MEDIA, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import config, fsx, gate, ledger  # noqa: E402
from paths import LIB, WORK  # noqa: E402

try:
    from mutagen import File as MFile          # a function, not a module
    from mutagen.id3 import ID3, TALB
    from mutagen.mp4 import MP4Tags
except ImportError:  # pragma: no cover - the gate reports this instead
    MFile = ID3 = MP4Tags = TALB = None

# Vorbis comments are behind a private class name. If it moves, every Vorbis file becomes
# "unsupported container" and is skipped, which is honest; guessing that an unknown dict
# is Vorbis is not.
try:
    from mutagen._vorbis import VCommentDict as VorbisTags
except ImportError:  # pragma: no cover
    VorbisTags = None

# Album strings that mean "no album". Matching on one would weld unrelated releases
# together, so they count as absent and are never written over. Kept identical to
# fix_grouping.py's set: two passes disagreeing about what counts as no-album would be a
# repair that undoes the other.
PLACEHOLDER_ALBUMS = frozenset({
    '', 'unknown album', 'album', 'title', 'untitled', 'no title', 'no album',
    'unnamed', 'n/a', 'na', 'none', 'unknown', 'music', 'songs', 'sounds',
})
PLACEHOLDER_PREFIXES = tuple(p for p in PLACEHOLDER_ALBUMS if ' ' in p)

# Titles that are not titles, for the same reason.
PLACEHOLDER_TITLES = frozenset({'', 'unknown title', 'title', 'track', 'unknown', 'song'})

# Top-level dirs whose name is not an artist identity, so nothing here may take an album
# name from a lookup keyed on that directory name.
UNTRUSTED_TOP = frozenset({'_Unsorted', '_mediatool', 'Unsorted', 'Unassigned'})

TMP_INFIX = '.identify-tmp-'
FLOOR_BYTES = 50 * 1000 * 1000 * 1000
USER_AGENT = 'lario-media/1.0 ( https://github.com/lariocpt/lario-llms )'
API_ROOT = 'https://musicbrainz.org/ws/2/'
# What MusicBrainz asks for. Slower is allowed; faster is what gets an IP throttled, and a
# run that got throttled mid-way would report a hit rate that is really a rate limit.
REQUEST_INTERVAL = 1.05
DEFAULT_CACHE = os.path.join(WORK, 'mb-lookup-cache.jsonl')


def tag_style(tags):
    """Which vocabulary a container speaks: 'id3', 'mp4', 'vorbis', or None.

    Keyed on the container, not the file handler, because the handler lies: a WAV carries
    an ID3 chunk and an AIFF carries one too, so dispatching on the handler's class name
    reads a real TALB as if it were a Vorbis comment and writes back garbage. None means
    this tool will not guess.
    """
    if ID3 is not None and isinstance(tags, ID3):
        return 'id3'
    if MP4Tags is not None and isinstance(tags, MP4Tags):
        return 'mp4'
    if VorbisTags is not None and isinstance(tags, VorbisTags):
        return 'vorbis'
    return None


def tidy(value):
    """The comparison key for a title or artist: case, accents and punctuation out.

    Different from ``album_key``, and deliberately so. This is for *matching* a filename,
    tag or MusicBrainz string to another, where "Beyoncé" and "Beyonce" and "Beyonce" must
    meet. ``album_key`` is for *identity* -- the exact album string as tagged -- and strips
    nothing beyond case and whitespace, because that is what the player groups on (§7.1).
    """
    if not value:
        return ''
    text = unicodedata.normalize('NFKD', str(value))
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[\u2018\u2019\u201b]', "'", text)
    text = re.sub(r'[^\w\s]+', ' ', text, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', text.casefold()).strip()


def album_key(value):
    """The album identity a player groups on: the string as tagged, case/whitespace only."""
    if value is None:
        return ''
    text = unicodedata.normalize('NFKC', str(value)).casefold()
    return re.sub(r'\s+', ' ', text).strip()


def is_placeholder(album_norm):
    """Is this album string a placeholder rather than a name.

    A placeholder phrase followed by more words is still that placeholder: this library
    holds ``Unknown Album 01 27 06 27 53 pm``, which an exact match would have treated as
    a real album and used to weld Black Keys to Blink 182.
    """
    if album_norm in PLACEHOLDER_ALBUMS:
        return True
    return any(album_norm.startswith(f'{phrase} ') for phrase in PLACEHOLDER_PREFIXES)


def _text(values):
    if isinstance(values, (list, tuple)):
        values = values[0] if values else None
    return None if values is None else str(values).strip() or None


FEAT = re.compile(r'\b(?:feat|ft|featuring|with|vs|versus|presented by)\b.*$', re.IGNORECASE)
SPLIT = re.compile(r'\s+(?:&|and|vs\.?|ft\.?|feat\.)\s+|\s*,\s*|\s*/\s*', re.IGNORECASE)


def artist_readings(value):
    """Every name an artist string can be read as.

    'A Tribe Called Quest & Busta Rhymes' is two artists to one side and one string to the
    other, and 'Artist feat. Someone' is one artist on both sides once the credit is
    dropped. Agreement is then set intersection, which is the honest shape: the pass may
    not decide that two strings are one artist by eyeballing a prefix.
    """
    if not value:
        return set()
    text = unicodedata.normalize('NFKC', str(value))
    out = set()
    for whole in (text, FEAT.sub('', text)):
        for piece in [whole] + SPLIT.split(whole):
            piece = tidy(piece)
            if len(piece) >= 2:
                out.add(piece)
    return out


def artists_agree(one, other):
    """Do two artist strings name the same artist, on at least one reading of each."""
    first, second = artist_readings(one), artist_readings(other)
    return bool(first and second and (first & second))


def read_one(path):
    """Tags + audio identity for one file. Never raises: an unreadable file is data.

    ``title`` is read here because it is the whole input to this pass. That is also the
    defect this file exists to correct once and for all: fix_grouping.py's reader returns
    album/artist/track and no ``title`` key, and a measurement that read ``rec['title']``
    off it reported "these files have no title either" from an **absent key**, not an empty
    tag. A missing key and an empty value are different facts.
    """
    record = {'path': path}
    try:
        stat = os.stat(path)
        record['size'] = stat.st_size
    except OSError as exc:
        record['error'] = f'stat: {exc}'
        return record
    try:
        handle = MFile(path)
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
        return record
    if handle is None:
        record['error'] = 'unrecognised file (mutagen returned nothing)'
        return record
    tags = handle.tags
    if tags is None:
        record['error'] = 'no tags readable by mutagen'
        return record
    info = getattr(handle, 'info', None)
    if info is not None:
        try:
            record['info'] = {'length': round(float(getattr(info, 'length', 0.0) or 0.0), 2),
                              'bitrate': int(getattr(info, 'bitrate', 0) or 0),
                              'sample_rate': int(getattr(info, 'sample_rate', 0) or 0),
                              'channels': int(getattr(info, 'channels', 0) or 0)}
        except (TypeError, ValueError) as exc:
            record['info_error'] = str(exc)
    style = tag_style(tags)
    record['style'] = style
    if style == 'id3':
        record['album'] = _text(tags.get('TALB'))
        record['title'] = _text(tags.get('TIT2'))
        record['artist'] = _text(tags.get('TPE1'))
        record['albumartist'] = _text(tags.get('TPE2'))
    elif style == 'mp4':
        record['album'] = _text(tags.get('\u00a9alb'))
        record['title'] = _text(tags.get('\u00a9nam'))
        record['artist'] = _text(tags.get('\u00a9ART'))
        record['albumartist'] = _text(tags.get('aART'))
    elif style == 'vorbis':
        record['album'] = _text(tags.get('album'))
        record['title'] = _text(tags.get('title'))
        record['artist'] = _text(tags.get('artist'))
        record['albumartist'] = _text(tags.get('albumartist') or tags.get('album artists'))
    else:
        record['error'] = f'unsupported tag container {type(tags).__name__}'
    return record


def top_of(dest, path):
    """The artist-level directory name, or None for a file loose in the library root."""
    relative = os.path.relpath(path, dest)
    parts = relative.split(os.sep)
    return parts[0] if len(parts) > 1 else None


def scan(dest, jobs):
    """Read every audio file under `dest` once. Returns (paths, records)."""
    extensions = gate.extensions_for('music')
    found = []
    for directory, _dirs, leaves in os.walk(dest):
        if os.path.basename(directory) == '_mediatool':
            continue                                  # this pass's own evidence
        for leaf in leaves:
            if os.path.splitext(leaf)[1].lower() in extensions:
                found.append(os.path.join(directory, leaf))
    found.sort()
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        records = list(pool.map(read_one, found))
    return found, records


def lucene(text):
    """A quoted phrase MusicBrainz will accept: reserved characters out, then quoted.

    Escaping them is also possible and was not chosen: a title that needs six backslashes
    searches worse than the same title with the punctuation dropped, because the match is
    on words either way.
    """
    cleaned = re.sub(r'[\\/"()\[\]{}*?!:^~\-+&|#]', ' ', str(text))
    return '"' + re.sub(r'\s+', ' ', cleaned).strip().replace('"', '') + '"'


def release_artist_names(release):
    """Every name the release is credited to, joined credits included."""
    names = []
    for credit in release.get('artist-credit') or []:
        if isinstance(credit, dict):
            if credit.get('name'):
                names.append(credit['name'])
            if (credit.get('artist') or {}).get('name'):
                names.append(credit['artist']['name'])
    return names


class MusicBrainz:
    """WS/2 recording search: one request per second, retried when busy, cached on disk.

    WS/1 is gone -- it answers 410 -- so this is the only API. The cache exists because the
    owner's rule is fewer re-reads, and because a run that is interrupted at minute forty
    should not pay for those forty minutes again. Entries are keyed on (title, artist)
    *without* duration, so the same lookup serves every copy of a track at any length: the
    duration test belongs to the decision, not to the query.
    """

    def __init__(self, cache_path=DEFAULT_CACHE, interval=REQUEST_INTERVAL, offline=False):
        self.cache_path = cache_path
        self.interval = interval
        self.offline = offline
        self.cache = {}
        self.last_request = 0.0
        self.requests = 0
        self.hits = 0
        self.errors = 0
        self.cache_error = None
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, encoding='utf-8') as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get('key'):
                        self.cache[tuple(row['key'])] = row.get('albums', [])
        self._out = None

    def _open(self):
        """Append handle for the cache. Losing it costs speed, not correctness -- but it
        is recorded, because a run that silently re-asked 3 000 questions would look like a
        run that was merely slow, and the difference shows up as a rate limit."""
        if self._out is None and self.cache_path:
            try:
                directory = os.path.dirname(self.cache_path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                self._out = open(self.cache_path, 'a', encoding='utf-8')
            except OSError as exc:
                self.cache_error = f'cache unwritable, lookups will not be reused: {exc}'
                self.cache_path = None
        return self._out

    def _get(self, endpoint, params):
        url = API_ROOT + endpoint + '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT,
                                                       'Accept': 'application/json'})
        last_error = 'unreachable'
        for attempt in range(5):
            wait = self.interval - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    self.requests += 1
                    return json.loads(response.read().decode('utf-8', 'replace'))
            except urllib.error.HTTPError as exc:
                self.requests += 1
                last_error = f'http {exc.code}'
                if exc.code in (429, 503):            # busy: back off, then try again
                    time.sleep(min(60.0, 2.0 ** attempt * 2))
                    continue
                if exc.code == 410:
                    raise RuntimeError('MusicBrainz WS/1 is retired; this build must use WS/2')
                raise
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                last_error = f'{type(exc).__name__}: {exc}'
                time.sleep(min(30.0, 2.0 ** attempt))
        self.errors += 1
        raise RuntimeError(last_error)

    def albums_for(self, title, artist):
        """Candidate albums for one recording, from the cache if it has them.

        Returns (albums, error). Each album is {'album', 'group', 'type', 'artists',
        'lengths'} -- lengths are the millisecond lengths of the recordings of it that the
        search actually returned, which is what makes the duration test possible.
        """
        key = (tidy(title), tidy(artist))
        if key in self.cache:
            self.hits += 1
            return self.cache[key], None
        if self.offline:
            return [], 'offline'
        payload = self._get('recording/', {'query': f'recording:{lucene(title)} AND '
                                                    f'artist:{lucene(artist)}',
                                           'limit': 25, 'fmt': 'json', 'inc': 'releases'})
        found = {}
        for recording in payload.get('recordings') or []:
            length = recording.get('length')
            for release in recording.get('releases') or []:
                group = release.get('release-group') or {}
                identity = group.get('id') or release.get('id')
                entry = found.setdefault(identity, {'album': release.get('title') or '',
                                                    'group': identity,
                                                    'type': group.get('primary-type'),
                                                    'artists': release_artist_names(release),
                                                    'lengths': []})
                if length:
                    entry['lengths'].append(int(length))
        self.cache[key] = list(found.values())
        handle = self._open()
        if handle is not None:
            handle.write(json.dumps({'key': list(key), 'albums': list(found.values())},
                                    ensure_ascii=False) + '\n')
            handle.flush()
        return list(found.values()), None


def build_twins(records):
    """Index of files that could answer someone else: titled, albumed, timed.

    An artist's own album tag is only evidence about a recording if the artist is attached
    to it, so both the track artist and the album artist are kept for the agreement test.
    """
    index = collections.defaultdict(list)
    for record in records:
        if record.get('error'):
            continue
        album = str(record.get('album') or '').strip()
        title = str(record.get('title') or '').strip()
        if not album or is_placeholder(album_key(album)):
            continue
        if not title or tidy(title) in PLACEHOLDER_TITLES:
            continue
        length = float((record.get('info') or {}).get('length') or 0.0)
        index[tidy(title)].append({'length': length, 'album': album,
                                   'artists': [record.get('artist'),
                                               record.get('albumartist')]})
    return index


def _winner(strings):
    """The most common exact spelling among candidates that share one album identity."""
    counts = collections.Counter(strings)
    distinct = {album_key(text) for text in strings}
    if len(distinct) != 1:
        return None, distinct
    return counts.most_common(1)[0][0], distinct


def twin_answer(index, record, artist, tolerance):
    """Fill from the library itself, or the reason it will not.

    The artist test is not paranoia: title plus duration alone matches a Bob Dylan file to
    a stranger's cover of the same song at the same length, and that is exactly the wrong
    album written into a gap where an honest ``[Unknown Album]`` used to be.
    """
    title = tidy(record['title'])
    length = float((record.get('info') or {}).get('length') or 0.0)
    if not title or title in PLACEHOLDER_TITLES:
        return None, 'no-title', []
    if not length:
        return None, 'no-duration', []
    matches = [twin for twin in index.get(title, ())
               if twin['length'] and abs(twin['length'] - length) <= tolerance
               and any(artists_agree(artist, candidate) for candidate in twin['artists']
                       if candidate)]
    if not matches:
        return None, 'no-twin', []
    album, distinct = _winner([twin['album'] for twin in matches])
    if album is None:
        return None, 'twins-disagree', sorted(distinct)
    return album, 'twin', [twin['album'] for twin in matches]


def build_folders(records):
    """Albums the files in each directory already assert, grouped by that directory."""
    folders = collections.defaultdict(list)
    for record in records:
        if not record.get('error'):
            folders[os.path.dirname(record['path'])].append(record)
    return folders


def build_album_sizes(records):
    """How many files the library already tags onto each album identity."""
    sizes = collections.Counter()
    for record in records:
        text = str(record.get('album') or '').strip()
        if text and not is_placeholder(album_key(text)):
            sizes[album_key(text)] += 1
    return sizes


MIN_TAGGED_SIBLINGS = 2


def folder_answer(folders, album_sizes, record):
    """Fill from the folder the file is standing in, or the reason it will not.

    This route was measured, applied to the live library, and undone in the same session,
    and the two guards below are what that cost taught. ``Artist/[Unknown Album]/`` is not
    an album folder: it is where the owner put everything that did not fit one, so a
    drawer's tags describe the drawer and not the record.

    * **two tagged siblings must agree, not one.**  ``Liquido/[Unknown Album]/`` holds four
      different files numbered ``01 -``, which is four singles; one tagged file named all
      twenty-three of them ``LIQUIDO``.
    * **the folder may not add more files than the album already has.**  An album does not
      grow by more than itself: ``Canibus/[Unknown Album]/`` wanted to add 39 files to
      ``Rip The Jacker``, which this library knows as 17 tracks.

    Both guards together take this route from 372 writes to 58, and what survives is the
    case it was written for -- ``Back in Black`` +1, ``Homework`` +7, ``2001`` +2. It is
    still the weakest route here, which is why its name is stamped on every line it writes
    in ``decisions.jsonl`` and why ``--undo --route folder`` can take exactly it back.
    """
    siblings = [other for other in folders.get(os.path.dirname(record['path']), ())
                if other is not record]
    strings = [str(other.get('album') or '').strip() for other in siblings]
    strings = [text for text in strings if text and not is_placeholder(album_key(text))]
    if not strings:
        return None, 'no-tagged-sibling', []
    album, distinct = _winner(strings)
    if album is None:
        return None, 'siblings-disagree', sorted(distinct)
    if len(strings) < MIN_TAGGED_SIBLINGS:
        return None, 'one-tagged-sibling', sorted(distinct)
    adding = 1 + sum(1 for other in siblings
                     if not str(other.get('album') or '').strip()
                     or is_placeholder(album_key(str(other.get('album') or ''))))
    size = album_sizes[album_key(album)]
    if adding > size:
        return None, 'folder-bigger-than-the-album', sorted(distinct)
    return album, 'folder', strings


def musicbrainz_answer(client, record, artist, tolerance):
    """Fill from MusicBrainz, or the reason it will not. Single winner or nothing."""
    length = float((record.get('info') or {}).get('length') or 0.0)
    if not length:
        return None, 'no-duration', []
    try:
        albums, error = client.albums_for(record['title'], artist)
    except Exception as exc:
        return None, f'mb-error: {type(exc).__name__}: {exc}', []
    if error:
        return None, f'mb-{error}', []
    if not albums:
        return None, 'mb-no-match', []
    on_albums = [album for album in albums if album.get('type') == 'Album']
    if not on_albums:
        return None, 'mb-no-album-release', sorted({row['album'] for row in albums})
    credited = [row for row in on_albums
                if any(artists_agree(artist, name) for name in row['artists']) or not row['artists']]
    if not credited:
        return None, 'mb-artist-mismatch', sorted({row['album'] for row in on_albums})
    timed = [row for row in credited
             if any(abs(row_length / 1000.0 - length) <= tolerance
                    for row_length in (row.get('lengths') or []))]
    if not timed:
        return None, 'mb-duration', sorted({row['album'] for row in credited})
    album, distinct = _winner([row['album'] for row in timed])
    if album is None:
        return None, 'mb-multiple-albums', sorted(distinct)
    return album, 'musicbrainz', [row['album'] for row in timed]


def apply_tags(path, wanted):
    """Write ``wanted`` ('album' only) into `path` -- a copy, never the library file.

    Which frame each format actually stores is taken from what this library's own tagged
    files use: TALB for MP3 and WAV, the iTunes ``\u00a9alb`` box for MP4, a Vorbis comment
    elsewhere. No other tag is touched, so an album fill cannot disturb the grouping that
    fix_grouping.py just repaired.
    """
    handle = MFile(path)
    if handle is None or handle.tags is None:
        raise ValueError('no tag container to write into')
    tags, style = handle.tags, tag_style(handle.tags)
    if style is None:
        raise ValueError(f'unsupported tag container {type(tags).__name__}')
    if 'album' not in wanted:
        raise ValueError('nothing to write')
    if style == 'id3':
        tags.add(TALB(encoding=3, text=[wanted['album']]))      # encoding 3 = UTF-8
    elif style == 'mp4':
        tags['\u00a9alb'] = [wanted['album']]
    else:
        tags['album'] = wanted['album']
    handle.save()


def clear_album(path):
    """Remove the album again -- the undo of a value that was absent."""
    handle = MFile(path)
    if handle is None or handle.tags is None:
        raise ValueError('no tag container to clear')
    tags, style = handle.tags, tag_style(handle.tags)
    try:
        if style == 'id3':
            tags.delall('TALB')
        elif style == 'mp4':
            del tags['\u00a9alb']
        elif style == 'vorbis':
            del tags['album']
        else:
            raise ValueError(f'unsupported tag container {type(tags).__name__}')
    except KeyError:
        pass                                          # already gone; undo is idempotent
    handle.save()


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
    if 'album' in wanted and record.get('album') != wanted['album']:
        return f'album reads {record.get("album")!r}, wanted {wanted["album"]!r}'
    if baseline_info is not None and record.get('info') != baseline_info:
        return (f'audio identity changed: {baseline_info} -> {record.get("info")} '
                '(duration/bitrate/sample-rate/channels must be untouched by a tag write)')
    return None


def protect_original(path, library, root):
    """Copy the untouched bytes to `root`, verified by SHA-256. The only safety net."""
    if root is None:
        return {'protected': None}
    target = os.path.join(root, os.path.relpath(path, library))
    if os.path.exists(target):
        return {'protected': target, 'skipped': True}
    receipt = fsx.copy_file(path, target, verify=True, digest=None)
    return {'protected': target, 'bytes': receipt['bytes'], 'sha256': receipt['sha256']}


def commit_one(action, library, protect_root, run_id, book, backup_handle):
    """Protect, fill, verify, swap, journal. One file, all or nothing.

    Verification runs twice -- on the staged copy before the swap and again on the library
    path after it -- because the promise is about the file at that path, not about the copy
    that was built.
    """
    path = action['path']
    wanted = {'album': action['album']}
    baseline = read_one(path)
    if baseline.get('error'):
        return {'ok': False, 'stage': 'read', 'error': baseline['error']}
    if mismatch(baseline, wanted, baseline.get('info')) is None:
        return {'ok': True, 'already': True}

    protection = protect_original(path, library, protect_root)
    temp = os.path.join(os.path.dirname(path), TMP_INFIX + os.path.basename(path))
    if os.path.exists(temp):
        # A leftover temp is evidence of an interrupted write. Refuse the file rather than
        # guessing which of the two copies the owner wants kept.
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
                                    'new': wanted, 'route': action['route']},
                                   ensure_ascii=False) + '\n')
    backup_handle.flush()
    os.fsync(backup_handle.fileno())
    book.record(run_id, 'tag', src=path, dst=path, bytes=baseline.get('size', 0),
                requested_by='music/identify_albums.py')
    return {'ok': True, 'protected': protection.get('protected'),
            'protected_bytes': protection.get('bytes', 0), 'size': baseline.get('size', 0)}


def restore_one(path, old, library, protect_root):
    """Put one file's album back exactly as the run found it -- including absent."""
    wanted, clearing = {}, []
    if old.get('album'):
        wanted['album'] = old['album']
    else:
        clearing.append('album')
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
            clear_album(temp)
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'temp': temp}
    back = read_one(temp)
    problem = mismatch(back, wanted, baseline.get('info'))
    if problem is None and clearing and back.get('album'):
        problem = f'album should be gone, reads {back.get("album")!r}'
    if problem:
        return {'ok': False, 'error': problem, 'temp': temp}
    os.replace(temp, path)
    _fsync_dir(os.path.dirname(path))
    return {'ok': True, 'protected': protection.get('protected')}


def decide(dest, records, routes, tolerance, client, budget):
    """What would be filled, and everything that would not be, with its reason.

    Returns (actions, decisions, counters, lookups). Every file that was considered gets a
    line in ``decisions.jsonl``: a refusal is a result and not a gap, and "we do not know"
    recorded is the only thing that later makes it possible to know.

    Routes are asked, not just tried in order: every offline route answers, so the report
    can say what each one is worth and how much they overlap. And two routes naming
    *different* albums is not a tie to be broken by precedence, it is the definition of no
    winner -- those files are refused and the disagreement is recorded.
    """
    index = build_twins(records)
    folders = build_folders(records)
    album_sizes = build_album_sizes(records)
    actions, decisions = {}, []
    counters = collections.Counter()
    would = collections.Counter()
    lookups = 0
    for record in records:
        path = record['path']
        if record.get('error'):
            counters['skipped: unreadable'] += 1
            continue
        top = top_of(dest, path)
        album = str(record.get('album') or '').strip()
        if album and not is_placeholder(album_key(album)):
            counters['skipped: album already tagged'] += 1
            continue
        if top is None or top in UNTRUSTED_TOP:
            counters['skipped: no artist directory'] += 1
            continue
        title = str(record.get('title') or '').strip()
        if not title or tidy(title) in PLACEHOLDER_TITLES:
            counters['skipped: no title'] += 1
            continue
        length = float((record.get('info') or {}).get('length') or 0.0)
        if not length:
            counters['skipped: no duration'] += 1
            continue
        artist = str(record.get('artist') or '').strip() or top
        counters['candidates'] += 1

        answers, refusals = [], []
        if 'twins' in routes:
            found, why, seen = twin_answer(index, record, artist, tolerance)
            (answers if found is not None else refusals).append(('twins', found, why, seen))
        if 'folder' in routes:
            found, why, seen = folder_answer(folders, album_sizes, record)
            (answers if found is not None else refusals).append(('folder', found, why, seen))
        for name, _found, _why, _seen in answers:
            would[f'would fill: {name}'] += 1
        if not answers and 'musicbrainz' in routes:
            if budget and lookups >= budget:
                refusals.append(('musicbrainz', None, 'lookup-budget', []))
            else:
                before = client.requests
                found, why, seen = musicbrainz_answer(client, record, artist, tolerance)
                if client.requests > before:
                    lookups += 1
                (answers if found is not None else refusals).append(
                    ('musicbrainz', found, why, seen))
                if found is not None:
                    would['would fill: musicbrainz'] += 1

        if len(answers) > 1:
            distinct = {album_key(found) for _name, found, _why, _seen in answers}
            if len(distinct) > 1:
                counters['refuse: routes-disagree'] += 1
                decisions.append({'path': path, 'title': title, 'artist': artist,
                                  'length': length, 'verdict': 'refuse',
                                  'reason': 'routes-disagree',
                                  'candidates': sorted({f'{name}:{found}' for name, found,
                                                        _why, _seen in answers})[:8]})
                continue
        if answers:
            route, answer, reason, seen = answers[0]
        else:
            refusal = '+'.join(why for _name, _f, why, _s in refusals) or 'no-route-answered'
            seen = [text for _n, _f, _w, batch in refusals for text in batch]
            counters[f'refuse: {refusal.split(":")[0]}'] += 1
            decisions.append({'path': path, 'title': title, 'artist': artist, 'length': length,
                              'verdict': 'refuse', 'reason': refusal,
                              'candidates': sorted(set(seen))[:8]})
            continue
        actions[path] = {'path': path, 'album': answer, 'route': route, 'title': title,
                         'artist': artist, 'old': {'album': album or None},
                         'candidates': sorted(set(seen))[:8]}
        counters[f'fill: {route}'] += 1
        decisions.append({'path': path, 'title': title, 'artist': artist, 'length': length,
                          'verdict': 'fill', 'reason': reason, 'album': answer,
                          'route': route, 'also': [name for name, _f, _w, _s in answers[1:]],
                          'candidates': sorted(set(seen))[:8]})
    counters.update(would)
    return actions, decisions, counters, lookups


def stratify(actions, count):
    """Pick `count` files spread across every route and format in the plan.

    Round-robin over (route, extension) buckets, biggest bucket first, so a 30-file sample
    cannot end up 30 MP3s from the twins route: the point of a sample is to have touched
    every code path that the full run will use.
    """
    buckets = {}
    for action in sorted(actions, key=lambda item: item['path']):
        key = (action['route'], os.path.splitext(action['path'])[1].lower())
        buckets.setdefault(key, []).append(action)
    queues = [queue for _, queue in
              sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    picked = []
    while len(picked) < count and any(queues):
        for queue in queues:
            if queue and len(picked) < count:
                picked.append(queue.pop(0))
    return picked


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='identify_albums.py', description=__doc__.strip().splitlines()[0],
        epilog='Plan-only unless --apply. Nothing here moves or deletes a file.')
    parser.add_argument('--dest', default=None, help='library to work on (default: the music library)')
    parser.add_argument('--routes', default='twins,folder',
                        help='routes to ask, in precedence order: twins,folder,musicbrainz. '
                             'The two default routes are offline and were measured good; '
                             'musicbrainz is opt-in and was measured bad (see this file\'s '
                             'docstring) -- name it only knowing that')
    parser.add_argument('--tolerance', type=float, default=2.5,
                        help='seconds of duration agreement required of any candidate '
                             '(default 2.5; the 2Pac "Changes" bootlegs are 10-60 s off)')
    parser.add_argument('--limit', type=int, default=0,
                        help='cap on MusicBrainz lookups this run (0 = no cap); pilot with 60')
    parser.add_argument('--cache', default=DEFAULT_CACHE,
                        help='lookup cache, reused across runs so nothing is asked twice')
    parser.add_argument('--apply', action='store_true', help='write tags; without this, only plan')
    parser.add_argument('--sample', type=int, default=0,
                        help='apply to N files, spread over routes and formats')
    parser.add_argument('--undo', metavar='RUN_ID', help='restore the album values a run changed')
    parser.add_argument('--route', choices=ROUTES, default=None, metavar='ROUTE',
                        help='with --undo: restore only the files that route wrote, leaving '
                             'the rest of the run in place')
    parser.add_argument('--protect-parent', default=config.REPAIR_ORIGINALS,
                        help='where original bytes go before a file is touched (the OTHER disk)')
    parser.add_argument('--no-protect', action='store_true',
                        help='skip the safety copy; refused unless --i-accept-no-backup is also given')
    parser.add_argument('--i-accept-no-backup', action='store_true')
    parser.add_argument('--jobs', type=int, default=12, help='reader threads (tags only, no audio)')
    parser.add_argument('--free-floor-gb', type=float, default=50.0,
                        help='refuse to write if a volume would fall below this much free')
    return parser.parse_args(argv)


ROUTES = ('twins', 'folder', 'musicbrainz')


def main(argv=None):
    args = parse_args(argv)
    dest = os.path.abspath(args.dest or LIB)
    floor_bytes = int(args.free_floor_gb * 1000 * 1000 * 1000)
    if args.undo:
        return do_undo(dest, args)
    if args.route:
        raise SystemExit('refused: --route only narrows an --undo.  To choose which routes '
                         'RUN, use --routes')

    routes = [route.strip() for route in args.routes.split(',') if route.strip()]
    unknown = [route for route in routes if route not in ROUTES]
    if unknown or not routes:
        raise SystemExit(f'refused: --routes must be some of {", ".join(ROUTES)} '
                         f'(got {args.routes!r})')
    missing = gate.missing_dependencies('music')
    if missing or MFile is None:
        raise SystemExit('refused: this pass needs mutagen.  '
                         'uv pip install --python media/.venv/bin/python mutagen==1.48.1')
    if not os.path.isdir(dest):
        raise SystemExit(f'refused: no library at {dest}')

    run_id, run_dir = gate.claim_run_dir(dest, 'music', 'idalbum')
    print(f'run      {run_id}\nlibrary  {dest}\nevidence {run_dir}\nroutes   {", ".join(routes)}')
    started = time.time()
    paths, records = scan(dest, args.jobs)
    print(f'  read {len(paths)} files in {time.time() - started:.0f}s '
          f'({sum(1 for r in records if not r.get("error"))} readable by mutagen)', flush=True)

    client = MusicBrainz(cache_path=args.cache if 'musicbrainz' in routes else None,
                         offline='musicbrainz' not in routes)
    actions, decisions, counters, lookups = decide(
        dest, records, routes, args.tolerance, client, args.limit)

    with open(os.path.join(run_dir, 'decisions.jsonl'), 'w', encoding='utf-8') as handle:
        for row in decisions:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    ordered = [actions[path] for path in sorted(actions)]
    with open(os.path.join(run_dir, 'actions.jsonl'), 'w', encoding='utf-8') as handle:
        for action in ordered:
            handle.write(json.dumps(action, ensure_ascii=False) + '\n')

    candidates = counters['candidates']
    lines = ['', f'candidates     {candidates} files with a title and no album',
             '']
    for reason in sorted(counters, key=lambda key: (-counters[key], key)):
        if reason in ('candidates',):
            continue
        share = 100.0 * counters[reason] / max(1, candidates if reason.startswith('refuse')
                                               else len(paths))
        lines.append(f'  {reason:<42} {counters[reason]:>6}  ({share:.0f}%)')
    lines += ['', f'MusicBrainz    {client.requests} requests, {client.hits} answered from cache, '
                  f'{lookups} new lookups',
              f'to write       {len(ordered)}', '']
    for action in ordered[:12]:
        lines.append(f'  {os.path.relpath(action["path"], dest)[:58]:60} '
                     f'-> {action["album"][:34]!r} [{action["route"]}]')
    if len(ordered) > 12:
        lines.append(f'  ... and {len(ordered) - 12} more in actions.jsonl')
    report = '\n'.join(lines)
    print(report)

    plan = {'run_id': run_id, 'dest': dest, 'routes': routes, 'tolerance': args.tolerance,
            'limit': args.limit, 'cache': client.cache_path,
            'protect': None if args.no_protect else os.path.join(args.protect_parent, run_id),
            'files_seen': len(paths),
            'files_readable': sum(1 for r in records if not r.get('error')),
            'files_to_write': len(ordered),
            'counters': dict(counters.most_common()),
            'mb_requests': client.requests, 'mb_cache_hits': client.hits,
            'decisions_sha256': hashlib.sha256(
                open(os.path.join(run_dir, 'decisions.jsonl'), 'rb').read()).hexdigest(),
            'actions_sha256': hashlib.sha256(
                open(os.path.join(run_dir, 'actions.jsonl'), 'rb').read()).hexdigest()}
    ledger.write_plan(run_dir, plan)
    with open(os.path.join(run_dir, 'SUMMARY.txt'), 'w', encoding='utf-8') as handle:
        handle.write(report + '\n')
    if not args.apply:
        print('\n# plan only -- nothing was written.  --apply to write, '
              '--apply --sample 30 to test on a spread first')
        return 0
    if args.no_protect and not args.i_accept_no_backup:
        raise SystemExit(f'refused: --no-protect needs --i-accept-no-backup too. This library '
                         f'({config.MUSIC_LIB}) has no second copy and its volume has no '
                         'snapshots.')
    return do_apply(dest, run_id, run_dir, ordered, args, floor_bytes)


def do_apply(dest, run_id, run_dir, ordered, args, floor_bytes):
    """Write the plan. Every file: protect, temp, fill, verify, swap, journal."""
    selected = [action['path'] for action in (stratify(ordered, args.sample)
                                              if args.sample else ordered)]
    if not selected:
        print('\n# nothing to write')
        return 0

    protect_root = None
    if not args.no_protect:
        protect_root = os.path.join(args.protect_parent, run_id)
        os.makedirs(protect_root, exist_ok=True)
        needed = sum(os.path.getsize(path) for path in selected if os.path.exists(path))
        free_there = gate.check_floor(protect_root, needed, floor_bytes)
        gate.check_floor(dest, 0, floor_bytes)
        print(f'protecting {len(selected)} originals -- {needed / 1e9:.1f} GB onto {protect_root} '
              f'({free_there / 1e9:.1f} GB free there)')
    else:
        print('NO PROTECTION COPY -- originals are not being kept anywhere')

    book = ledger.Ledger(dest, apply=True)
    book.start_run(run_id, 'music', 'identify-albums', 'identify_albums', [dest], dest,
                   {'routes': args.routes, 'tolerance': args.tolerance, 'sample': args.sample,
                    'limit': args.limit, 'protect': protect_root})
    by_path = {item['path']: item for item in ordered}
    written = already = failed = 0
    failures = []
    started = time.time()
    with open(os.path.join(run_dir, 'tag-backup.jsonl'), 'a', encoding='utf-8') as backup:
        for index, path in enumerate(selected, 1):
            action = by_path[path]
            try:
                result = commit_one(action, dest, protect_root, run_id, book, backup)
            except Exception as exc:                       # one bad file must not stop the run
                result = {'ok': False, 'stage': 'exception',
                          'error': f'{type(exc).__name__}: {exc}'}
            if result.get('ok'):
                if result.get('already'):
                    already += 1
                else:
                    written += 1
            else:
                failed += 1
                failures.append(dict(result, path=path))
            if index % 250 == 0:
                print(f'  {index}/{len(selected)}  written={written} already={already} '
                      f'failed={failed}  {time.time() - started:.0f}s', flush=True)
    book.finish_run(run_id, 'done', {'written': written, 'already': already, 'failed': failed})

    lines = ['', '-- applied --',
             f'tags written   {written}   already correct {already}   refused/failed {failed}',
             f'protect copy   {protect_root or "NONE"}',
             f'undo with      --undo {run_id}   (album values; originals are in the protect copy)',
             f'elapsed        {time.time() - started:.0f}s']
    if failures:
        detail = os.path.join(run_dir, 'failures.jsonl')
        with open(detail, 'w', encoding='utf-8') as handle:
            for row in failures:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        lines.append(f'failures       {detail} ({len(failures)} lines)')
        for row in failures[:8]:
            lines.append(f'  {row.get("stage")}: {row["path"]} -- {row["error"]}')
    lines += ['', 'Navidrome will not notice until it rescans: in the web UI use Settings -> '
                  'Rescan library, or `docker exec navidrome sh -c "kill -HUP 1"`.']
    report = '\n'.join(lines)
    with open(os.path.join(run_dir, 'APPLY.txt'), 'w', encoding='utf-8') as handle:
        handle.write(report + '\n')
    print(report)
    return 0 if not failed else 1


def select_route(lines, route):
    """The rows of a run that one route wrote, or every row when no route is named.

    Kept separate from ``do_undo`` because it is the part that decides what a partial undo
    touches: an empty result must be an error, not a silent success, and a row stamped with
    no route at all must never be swept into a narrowed undo.
    """
    if not route:
        return lines
    return [line for line in lines if line.get('route') == route]


def do_undo(dest, args):
    """Put album values back exactly as the named run found them.

    ``--route`` narrows an undo to the files ONE route wrote, because routes are trusted
    unequally and a run that mixes them should not have to be undone all-or-nothing. The
    route is stamped on every row of ``tag-backup.jsonl``, which is the record of what was
    written, so the narrowing reads the same file the full undo does and cannot quietly
    restore more than it was asked to.
    """
    source = gate.evidence_dir(dest, args.undo)
    backup = os.path.join(source, 'tag-backup.jsonl')
    if not os.path.exists(backup):
        raise SystemExit(f'refused: no tag backup for run {args.undo} at {backup}')
    with open(backup, encoding='utf-8') as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    kept = select_route(lines, args.route)
    if args.route and not kept:
        raise SystemExit(f'nothing to undo: run {args.undo} wrote no files by route '
                         f'{args.route!r} ({len(lines)} files, routes '
                         f'{sorted({line.get("route") for line in lines})})')
    if args.route:
        print(f'# narrowing to route {args.route}: {len(kept)} of {len(lines)} files')
        lines = kept
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
            result = restore_one(line['path'], line.get('old') or {}, dest, protect_root)
        except Exception as exc:
            result = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        if result.get('ok'):
            restored += 1
        else:
            failed += 1
            failures.append(dict(result, path=line['path']))
        # Journal every restore, not just the failures. An undo that leaves no trace is a
        # hole in the record of what the library currently is: two runs can write the same
        # file, and only the events in order say which value is live.
        journal.write(json.dumps({'path': line['path'],
                                  'route': line.get('route'),
                                  'restored_to': (line.get('old') or {}).get('album'),
                                  'had_been': (line.get('new') or {}).get('album'),
                                  'ok': bool(result.get('ok'))}, ensure_ascii=False) + '\n')
        if (restored + failed) % 250 == 0:
            print(f'  {restored + failed}/{len(lines)} restored={restored} failed={failed}',
                  flush=True)
    journal.close()
    with open(os.path.join(undo_dir, 'SUMMARY.txt'), 'w', encoding='utf-8') as handle:
        handle.write(f'undo of {args.undo}'
                     f'{" narrowed to route " + args.route if args.route else ""}\n'
                     f'files {len(lines)}  restored {restored}  failed {failed}\n'
                     f'journal {journal_path}\n')
    print(f'\nrestored {restored}, failed {failed}.')
    if failures:
        detail = os.path.join(undo_dir, 'failures.jsonl')
        with open(detail, 'w', encoding='utf-8') as handle:
            for row in failures:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(f'failures: {detail}')
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
