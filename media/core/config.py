#!/usr/bin/env python3
"""Every path these tools touch, in one place, overridable by environment.

Each domain used to hard-code its own copy of the same roots: `W` alone appeared
in 40 photo scripts, `LIB` in 21 of them and again in 9 music scripts with a
*different* meaning. A moved library therefore meant 40 edits, and every missed
one was a chance for a destructive pass to run against the wrong tree. Resolve
them here instead.

Override for a different machine or a dry run against a copy:

    LARIO_PHOTO_LIB=/tmp/pics-clone LARIO_MUSIC_STAGE=/tmp/stage ...

The per-domain `paths.py` beside each corpus re-exports these under the short
names the existing code already uses (`W`, `LIB`, `VIDLIB`, `HHD`, `STAGE`,
`DB`), so the scripts run unchanged from their new directory.

Nothing in this module creates, moves, or deletes anything: it resolves names,
and it is the only file in the toolkit allowed to spell out where things live.
"""
import os


def _path(variable, default):
    """Environment override wins; the value is never validated, only reported."""
    return os.environ.get(variable, default)


# ---------------------------------------------------------------- libraries
# Destinations. These are the paths that matter: a pass writes here.
PHOTO_LIB = _path("LARIO_PHOTO_LIB", "/home/lario/Pictures/Photos")
# The video half of the photo set: same `YYYY/YYYY-MM-DD <Event>` shape as
# PHOTO_LIB, and it is the tree the 2026 photo pass actually filed into (427
# clips, years 2005-2018 + Undated). The default used to be /mnt/xfs/videos/videos,
# a tree that no longer exists, so every day looked new and no video counted as a
# survivor -- audit_coverage and check_zips resolved `dest` paths to nothing.
VIDEO_LIB = _path("LARIO_VIDEO_LIB", "/mnt/media/videos")
MUSIC_LIB = _path("LARIO_MUSIC_LIB", "/mnt/xfs/music")
MOVIES = _path("LARIO_MOVIES", "/mnt/media/movies")
SERIES = _path("LARIO_SERIES", "/mnt/media/series")
AUDIOBOOKS = _path("LARIO_AUDIOBOOKS", "/mnt/media/audiobooks")
BOOKS = _path("LARIO_BOOKS", "/mnt/media/books")

# The calibre-web drop. Anything placed here is picked up by the ebook library;
# audiobooks.in.drlario.org is a different service (audiobookshelf) and does not
# read it. Dedupe against BOOKS/library before ever writing here.
BOOK_IMPORT = _path("LARIO_BOOK_IMPORT", BOOKS + "/import")
# ebooks found inside audiobook boxes are parked here: they are not part of
# the shelf, and deleting them was not authorised either.
BOOK_PARK = _path("LARIO_BOOK_PARK", BOOKS + "/_from-audiobooks")

# The rebuild's staging tree. `Photos.new` was the tree being written while
# `Photos` was still live, and several scripts called one of the *two* `NEW`:
# mostly the staging tree, twice the finished library. Spelling them as separate
# names is the whole point -- a pass aimed at the wrong one moves the library.
PHOTO_STAGING = _path("LARIO_PHOTO_STAGING", PHOTO_LIB + ".new")

# Read-only original backup. Nothing in the toolkit writes here; the delete-gating
# passes read it only to prove a byte already exists somewhere safe.
PHOTO_BACKUP = _path("LARIO_PHOTO_BACKUP", "/mnt/xfs/photos-originals-backup")
PHOTO_BACKUP_PHOTOS = _path("LARIO_PHOTO_BACKUP_PHOTOS", PHOTO_BACKUP + "/Photos")

# Staging area for the mini-player's export: not a library, and nothing here is
# authoritative -- it is only ever a source until a verified copy lands in one.
MUSIC_STAGE = _path("LARIO_MUSIC_STAGE", "/mnt/xfs/staging-mini-music")

# Third source of the photo set, still arriving from an external drive.
HHD = _path("LARIO_HHD",
            "/home/lario/Documents/from hhd/iMac April 2020/"
            "Lario External Backup Lacie/Work MacBook Pro")

# Things that are not files we can file anywhere: unplayable media, sidecars,
# torrent notices. Archived with an INDEX.txt, never thrown away, never indexed
# as if it were part of a library.
PRESERVED = _path("LARIO_PRESERVED", "/mnt/xfs/preserved-video")
PRESERVED_MINI = _path("LARIO_PRESERVED_MINI", "/mnt/xfs/preserved-mini")
PRESERVED_MUSIC = _path("LARIO_PRESERVED_MUSIC", "/mnt/xfs/preserved-music")
PRESERVED_AUDIOBOOKS = _path("LARIO_PRESERVED_AUDIOBOOKS", "/mnt/xfs/preserved-audiobooks")

# ---------------------------------------------------------------- scratch
# Where each pass keeps its own evidence: jsonl audits, manifests, hash caches.
# Evidence belongs with the job, not inside the library it describes.
# These defaults are the 2026 job directories, and three of the four were deleted
# in the corpora move: only ~/audiobook-reorganize survives. Nothing inherits them
# any more -- every command reads the root from here instead of spelling it out --
# so a run points at a directory that exists:
#
#     W=~/media-evidence/photos-2026-11 python3 media/photos/verify_final.py
#
# and it is created on demand. A driver run takes that further and defaults the
# root to <dest>/_mediatool/<run_id>/ (PLAN.md 4.3.4), which is where it belongs.
PHOTO_WORK = _path("W", os.path.expanduser("~/photos-reorg-work"))
VIDEO_WORK = _path("LARIO_VIDEO_WORK", os.path.expanduser("~/video-reorganize"))
MUSIC_WORK = _path("LARIO_MUSIC_WORK", os.path.expanduser("~/music-reorganize"))
AUDIOBOOK_WORK = _path("LARIO_AUDIOBOOK_WORK", os.path.expanduser("~/audiobook-reorganize"))

# The shelf merger's audit trail: one `{"src":..., "dst":...}` line per moved
# file. The cover/leftover filing needs it to know which book a stray sidecar
# belonged to, so it is a name worth resolving rather than guessing.
SANDERSON_LOG = _path("SANDERSON_LOG", AUDIOBOOK_WORK + "/sanderson-merge.jsonl")

# The tidy pass's move audit -- the only way back from an --apply, so a test or an
# experiment must not be able to append to it. Overridable for that reason alone;
# it lives beside the tool that writes it and is gitignored there.
TIDY_AUDIT = _path("LARIO_TIDY_AUDIT",
                   os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "tidy-library.jsonl"))

# The photo import plan is *hand-edited*: it is the one artifact a human edits
# between runs, and the only way in is PLAN=. It stays outside the repo (it is
# tens of megabytes of per-file job data, regenerated by plan_import.py).
PHOTO_PLAN = _path("PLAN", PHOTO_WORK + "/import-plan.json")

# ---------------------------------------------------------------- services
# Read-only indexes owned by other services. mode=ro is deliberate: a music pass
# that could write Navidrome's schema would be able to lose the library.
NAVIDROME_DB = _path("LARIO_NAVIDROME_DB",
                     "file:" + os.path.expanduser("~/srv/navidrome/navidrome.db") + "?mode=ro")

# ffmpeg is pinned: the build on PATH has changed behaviour under other jobs.
FFMPEG = _path("LARIO_FFMPEG", "/usr/bin/ffmpeg")
FFPROBE = _path("LARIO_FFPROBE", "/usr/bin/ffprobe")
