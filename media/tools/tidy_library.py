#!/usr/bin/env python3
"""File what the libraries are not supposed to serve. Move-only; dry-run first.

Five independent passes:

  sanderson-sidecars   the covers, `.opf` and `.m3u` the shelf merger left behind
                       in the two old Brandon Sanderson trees. Each one goes into
                       the book folder its audio ended up in, read from the merge
                       log -- an image beside a book is what a shelf wants. A
                       playlist is NOT: the merger renamed every file, so every
                       `.m3u` in the old trees points at paths that no longer
                       exist, and those are archived instead of shelved.

  music-sidecars       CD-rip and scene sidecars sitting inside the music library
                       (`.log` `.cue` `.accurip` `.toc` `.sfv` `.srr` `.md5`
                       `.nfo`, `DR*.txt`/`auCDtect.txt`, and the `_ORGANIZE_*`
                       files a finished import left at the library root). Album
                       art is not litter and stays where it is. Navidrome never
                       indexed any of these, so removing them cannot change what
                       the server serves.

  mini-stage           what the mini-player export left in its staging tree after
                       the audio was imported: cover images, scene `.nfo`/`.sfv`/
                       `.m3u`, a `.doc`, an `.asx`, and one bonus concert `.avi`.
                       The staging tree is not a library, so this is a tidy, not
                       a re-import.

  nested-movies        a film filed inside another film's folder. A scanner still
                       finds it, so it can sit unnoticed for years while the top
                       of the library lies about what it holds -- and it hides
                       the filed copy from every check that reads the library at
                       its top. Only the accidental-nesting signature qualifies:
                       its own feature-length video, a parent that holds one too,
                       and two clearly different titles.

  video-litter         three things that make a movie library lie about itself: a
                       top-level folder holding no playable file at all (a
                       multi-part `.rar` of a film that is already filed),
                       `.aspect` player sidecars, and extension-less video that no
                       scanner can see. The two risky ones are only touched when a
                       filed copy of the same title exists, and the extension-less
                       file must probe identical (codec, frame size, duration)
                       first -- otherwise a failed extraction that happens to be
                       the only copy gets archived out of reach.

Nothing here deletes anything. `--apply` moves each file to its book folder or to
the mirrored path under a preserved tree, appends an INDEX.txt section there
saying where it came from, and appends every move to tidy-library.jsonl. Same-
filesystem moves are renames; a cross-filesystem move is md5-verified after the
copy and only then releases the source. `--undo` replays the audit backwards.

  python3 tidy_library.py                          # plan every pass
  python3 tidy_library.py music-sidecars --apply
  python3 tidy_library.py video-litter --apply --prune-empty
  python3 tidy_library.py --undo music-sidecars
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import config as _config            # noqa: E402

AUDIO = {".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".wav", ".flac", ".aiff", ".dsf"}
VIDEO = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".mpg", ".mpeg", ".ts",
         ".m2ts", ".vob", ".iso", ".webm", ".flv", ".ogv", ".divx"}
IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}

# What a music folder should not contain. Art is deliberately absent: covers
# belong with the album, and Navidrome ignores both kinds either way.
MUSIC_LITTER = {".log", ".cue", ".accurip", ".toc", ".sfv", ".srr", ".md5",
                ".nfo", ".tsv", ".txt"}
# Playlists whose entries the shelf merger invalidated.
BROKEN_PLAYLISTS = {".m3u", ".m3u8", ".pls"}
# Per-video player overrides: litter beside a real file, so matched separately.
PLAYER_SIDECARS = {".aspect"}

PACKAGING = {".nfo", ".sfv", ".m3u", ".m3u8", ".pls", ".asx", ".srr", ".url",
             ".doc", ".docx", ".sample"}

# One film filed INSIDE another film's folder: a folder that holds its own
# feature-length video while its parent folder holds one too. The names below
# say "supplementary" rather than "a second work", and `cd1` / `disc2` / `pt3`
# say "the same film, in pieces" -- none of them is a candidate.
EXTRAS = {"extras", "bonus", "bonus features", "featurettes", "special features",
          "deleted scenes", "backstage", "behind the scenes", "interviews",
          "documentary", "sample", "samples", "trailer", "trailers", "subs",
          "subtitles", "misc"}
NUMERIC_PART = re.compile(r"^(cd|disc|disk|part|pt)[\s_]*\d+[a-z]?$", re.I)
YEAR = re.compile(r"\((?:19|20)\d\d\)")
FEATURE_BYTES = 200_000_000

AUDIT = Path(_config.TIDY_AUDIT)   # overridable: a test run must not append to
                                   # the audit `--undo` replays
PASSES = ("sanderson-sidecars", "music-sidecars", "mini-stage", "nested-movies",
          "video-litter")
ARCHIVES = ("PRESERVED", "PRESERVED_MINI", "PRESERVED_MUSIC", "PRESERVED_AUDIOBOOKS")

OLD_TREES = ("The Cosmere Series - Brandon Sanderson", "Brandon Sanderson collection")


# ------------------------------------------------------------------ plumbing
def walk(root):
    root = Path(root)
    if not root.is_dir():
        return
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            yield Path(dirpath) / fn


def probe(path):
    """codec, frame size and duration -- enough to call two files the same cut."""
    try:
        out = subprocess.run(
            [_config.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height",
             "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=120).stdout
        j = json.loads(out or "{}")
        st = (j.get("streams") or [{}])[0]
        return (st.get("codec_name"), st.get("width"), st.get("height"),
                round(float(j.get("format", {}).get("duration", 0)), 1))
    except Exception:
        return None


def normalise(text):
    t = unicodedata.normalize("NFKC", str(text)).casefold()
    t = re.sub(r"\((?:19|20)\d\d\)", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Words that identify nothing: filler, the author's own name, the series names
# every folder on the shelf carries, and the edition labels the merger wrote in.
# Dropping them is what makes a leftover image attributable to ONE book.
STOPWORDS = {"the", "and", "for", "with", "part", "cover", "brandon", "sanderson",
             "graphic", "audio", "unabridged", "abridged", "normal", "digital",
             "release", "volume", "novel", "mistborn", "stormlight", "archive",
             "elantris", "collected", "tales",
             # generic sidecar names: they say what kind of file it is, never
             # which book, so they must not be read as a title
             "metadata", "info", "readme", "folder", "poster", "backdrop",
             "extra", "artwork", "opf"}


def tokens(text):
    return {w for w in normalise(text).split() if len(w) >= 3 and w not in STOPWORDS}


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def unique(dst):
    """Never overwrite. A collision keeps both, naming the folder it came from."""
    if not dst.exists():
        return dst
    stem, suffix, parent = dst.stem, dst.suffix, dst.parent
    tag = re.sub(r"[^\w.+ -]", "_", parent.name)[:40]
    for n in range(1, 1000):
        cand = parent / f"{stem} [was in {tag}]{' (%d)' % n if n > 1 else ''}{suffix}"
        if not cand.exists():
            return cand
    raise RuntimeError("too many collisions for %s" % dst)


def _nearest(path):
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def tree_size(path):
    """Bytes a move carries. For a filed folder that is everything inside it, so
    a report about an 8.8 GB film does not read as 0.000 GB."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _same_fs(src, dst):
    """True when a rename would work; different devices need a copy plus verify."""
    try:
        return os.lstat(src).st_dev == os.lstat(_nearest(dst.parent)).st_dev
    except OSError:
        return False


def relocate(moves, event="move", pass_name=None):
    """Move every planned file. Returns one record per file that actually moved,
    with the destination it really landed on (a collision renames) and the size
    measured before the move, so a report written afterwards still adds up.

    Never overwrites, never truncates a destination it did not verify: the
    cross-device path copies to `.part`, checks size and md5, and only then
    releases the source."""
    results = []
    missing = 0
    for src, dst, why in moves:
        if not src.exists():
            missing += 1      # planned against one state of the tree, applied
            continue          # after something else moved that path
        size = tree_size(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        target = unique(dst)
        if src.is_dir():
            # A filed folder moves by rename or not at all: verifying a copy of a
            # whole tree is a different job, and no pass plans one across devices.
            if not _same_fs(src, target):
                raise RuntimeError("refusing an unverified cross-device folder move: %s" % src)
            shutil.move(str(src), str(target))
        elif _same_fs(src, target):
            shutil.move(str(src), str(target))
        else:
            part = target.with_name(target.name + ".part")
            shutil.copy2(str(src), str(part))
            if part.stat().st_size != size:
                part.unlink()
                raise RuntimeError("size changed mid-copy: %s" % src)
            if md5(part) != md5(src):
                part.unlink()
                raise RuntimeError("checksum mismatch, source kept: %s" % src)
            os.replace(str(part), str(target))
            src.unlink()
        record = {"pass": pass_name, "src": str(src), "dst": str(target),
                  "why": why, "bytes": size}
        results.append(record)
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "ev": event, **record}) + "\n")
    if missing:
        print("    %d planned file(s) no longer where they were planned -- skipped" % missing)
    return results


def prune_empty(dirs):
    """Remove only directories this pass emptied, deepest first.

    `rmdir` cannot delete a directory that still holds something, so a mis-plan
    cannot take a library with it: the worst case here is that it prints nothing.
    The removal is audited, and restoring a file recreates its directories."""
    removed = []
    for top in dirs:
        for candidate in sorted(Path(top).rglob("*"), reverse=True):
            if candidate.is_dir():
                try:
                    candidate.rmdir()
                    removed.append(candidate)
                except OSError:
                    pass
        try:
            Path(top).rmdir()
            removed.append(Path(top))
        except OSError:
            pass
    for path in removed:
        with open(AUDIT, "a") as fh:
            fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "ev": "rmdir", "src": str(path), "bytes": 0}) + "\n")
    return removed


def archive_of(path):
    """Which preserved tree this destination is inside, or None for a filing
    that stays in a library (the Sanderson covers)."""
    for name in ARCHIVES:
        root = Path(getattr(_config, name))
        try:
            Path(path).relative_to(root)
            return root
        except ValueError:
            continue
    return None


def write_index(preserved, title, results):
    """Append, never clobber: a preserved tree already carries earlier sections."""
    preserved.mkdir(parents=True, exist_ok=True)
    index = preserved / "INDEX.txt"
    total = sum(r["bytes"] for r in results)
    with open(index, "a") as fh:
        fh.write("\n%s\n"
                 "  %s  %d files, %.1f MB\n"
                 "  why: %s\n"
                 "  Each pair is the archived path and the exact place it came from. Nothing\n"
                 "  here was deleted: tidy_library.py --undo <pass> replays these moves back.\n"
                 % (title, time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
                    len(results), total / 1e6, results[0]["why"]))
        for r in results:
            fh.write("    %s\n        was %s\n"
                     % (os.path.relpath(r["dst"], preserved), r["src"]))


def report(pass_name, moves, where):
    total = sum(tree_size(p) for p, _, _ in moves if p.exists())
    label = "entries" if any(p.is_dir() for p, _, _ in moves) else "files"
    print("%s: %d %s, %.1f MB -> %s" % (pass_name, len(moves), label, total / 1e6, where))
    by = {}
    for src, _, why in moves:
        row = by.setdefault(why, [0, 0])
        row[0] += 1
        row[1] += tree_size(src) if src.exists() else 0
    for why, (n, size) in sorted(by.items(), key=lambda kv: -kv[1][1]):
        print("    %5d  %8.3f GB  %s" % (n, size / 1e9, why))
    for src, dst, _ in moves[:6]:
        print("       %s\n            -> %s" % (src, dst))
    if len(moves) > 6:
        print("       ... %d more" % (len(moves) - 6))
    return total


# ------------------------------------------------------------ the four passes
def plan_sanderson(log_path):
    """Old-tree leftovers -> the book folder their audio went to.

    The merge log is the only record of which old folder became which book, so
    map its parent directories. A sidecar sitting a level above the audio is fine
    as long as every file beneath it went to one single book; if it spans books
    there is no honest answer, so it is left where it is and reported."""
    book_of = {}
    log = Path(log_path)
    if not log.is_file():
        raise SystemExit("no merge log at %s -- the shelf merger's audit is what "
                         "says which book a sidecar belongs to" % log)
    for line in log.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("src") and rec.get("dst"):
            book_of.setdefault(str(Path(rec["src"]).parent), Path(rec["dst"]).parent)

    def book_for(folder):
        folder = str(folder)
        if folder in book_of:
            return book_of[folder]
        below = {str(v) for k, v in book_of.items() if k.startswith(folder + os.sep)}
        if len(below) == 1:
            return Path(below.pop())
        if len(below) > 1:
            # a sidecar one level above several books: attribute it by title, and
            # by which tree it came from, rather than guessing a shelf
            return None
        for parent in Path(folder).parents:
            if str(parent) in book_of:
                return book_of[str(parent)]
        return None

    def by_title(stem, edition):
        """Fallback for a sidecar that sits above several books: shelve it by the
        title in its own filename. Only discriminative evidence counts -- a token
        that belongs to exactly one book on the shelf -- and the tree it came from
        settles an edition tie (the collection is the unabridged recordings)."""
        toks = tokens(stem)
        if not toks:
            return None
        hits = sorted({b for t in toks for b in token_books.get(t, ())})
        if len(hits) == 1:
            return hits[0]
        rare = {next(iter(token_books[t])) for t in toks if len(token_books.get(t, ())) == 1}
        if len(rare) == 1:
            return rare.pop()
        if rare and edition:
            chosen = [b for b in rare if edition.lower() in b.stem.lower()]
            if len(chosen) == 1:
                return chosen[0]
        return None

    books = sorted({b for b in book_of.values()})
    token_books = {}
    for book in books:
        for tok in tokens(book.stem):
            token_books.setdefault(tok, set()).add(book)

    moves, parked = [], []
    for tree in OLD_TREES:
        root = Path(_config.AUDIOBOOKS) / tree
        edition = "Unabridged" if tree.startswith("Brandon Sanderson collection") else "GraphicAudio"
        for src in walk(root):
            ext = src.suffix.lower()
            if ext in AUDIO:
                continue
            if ext in BROKEN_PLAYLISTS:
                moves.append((src, Path(_config.PRESERVED_AUDIOBOOKS)
                              / root.name / src.relative_to(root),
                              "playlist naming the pre-merge filenames"))
                continue
            # a sidecar called "cover.jpg" says nothing about its book; the folder
            # it was filed in does, so fall back to that for generic names
            evidence = src.stem if tokens(src.stem) else src.parent.name
            book = book_for(src.parent) or by_title(evidence, edition)
            if book is None:
                # Nothing identifies which book it belongs to, and these trees sit
                # inside the audiobook library root: park it with an index rather
                # than leave litter where a server scans. Guessing a shelf would
                # attach the wrong cover to a book, which is worse.
                parked.append(src)
                moves.append((src, Path(_config.PRESERVED_AUDIOBOOKS)
                              / root.name / src.relative_to(root),
                              "no book attributable from the merge log or its name"))
                continue
            moves.append((src, book / src.name, "shelved with its book"))
    husks = [Path(_config.AUDIOBOOKS) / name for name in OLD_TREES
             if (Path(_config.AUDIOBOOKS) / name).is_dir()]
    return moves, parked, husks


def plan_music():
    lib = Path(_config.MUSIC_LIB)
    moves = []
    for src in walk(lib):
        ext = src.suffix.lower()
        if ext in AUDIO or ext in IMAGE:
            continue
        if ext in MUSIC_LITTER:
            moves.append((src, Path(_config.PRESERVED_MUSIC) / src.relative_to(lib),
                          "rip/scene sidecar inside the music library"))
    return moves


def plan_mini_stage():
    stage = Path(_config.MUSIC_STAGE)
    moves = []
    for src in walk(stage):
        ext = src.suffix.lower()
        if ext in AUDIO:
            continue
        if ext in IMAGE:
            kind = "cover image left after the import (26 of these already exist in the library)"
        elif ext in PACKAGING:
            kind = "release packaging"
        else:
            kind = "video that is not audio, never indexed by anything"
        moves.append((src, Path(_config.PRESERVED_MINI) / src.relative_to(stage), kind))
    return moves


def is_spool(path):
    """Multi-part release machinery: no curated library entry ever has these."""
    ext = path.suffix.lower()
    return bool(re.match(r"^\.[rn]\d\d$", ext)) or ext in {
        ".sfv", ".srr", ".par2", ".001", ".rar", ".yenc", ".url"}


def plan_video():
    moves, orphans, empties = [], [], []
    for library in (_config.MOVIES, _config.SERIES):
        lib = Path(library)
        if not lib.is_dir():
            continue
        contents = {}
        for entry in sorted(p for p in lib.iterdir() if p.is_dir()):
            files = list(walk(entry))
            contents[entry] = [p for p in files if p.suffix.lower() in VIDEO]
        filed = {}
        for entry, plays in contents.items():
            if plays:
                filed.setdefault(normalise(entry.name), []).append(entry)

        for entry, plays in contents.items():
            files = [p for p in walk(entry)]
            twins = [t for t in filed.get(normalise(entry.name), []) if t != entry]
            best_twin = max((p.stat().st_size for t in twins for p in contents[t]), default=0)
            best_own = max((p.stat().st_size for p in plays), default=0)
            if plays and twins and any(is_spool(p) for p in files) and best_twin > best_own:
                # an unprocessed download spool of a film that is filed, properly,
                # elsewhere in the library: the rar parts, the sample and the
                # half-extracted CD1 all go. Only when the filed copy is the
                # bigger one, so the better version is never the one archived.
                moves += [(p, Path(_config.PRESERVED) / p.relative_to(lib),
                           "unprocessed release spool; a larger copy of the title is filed here")
                          for p in files]
                empties.append(entry)
                continue
            if plays:
                moves += [(p, Path(_config.PRESERVED) / p.relative_to(lib),
                           "player aspect override beside the video")
                          for p in files if p.suffix.lower() in PLAYER_SIDECARS]
                continue
            if twins:
                # no playable file anywhere, and the title IS filed: this is litter
                moves += [(p, Path(_config.PRESERVED) / p.relative_to(lib),
                           "folder holding no playable file; the title is filed here")
                          for p in files]
                empties.append(entry)
                continue
            orphans.append(entry)

        for src in sorted(p for p in lib.iterdir() if p.is_file() and not p.suffix):
            mine = probe(src)
            key = normalise(src.name)
            twin = None
            for name, plist in filed.items():
                if key and (key in name or name in key):
                    if any(probe(p) == mine for t in plist for p in contents[t]):
                        twin = plist[0]
                        break
            if mine and twin:
                moves.append((src, Path(_config.PRESERVED) / src.name,
                              "extension-less duplicate: identical codec, frame size, duration"))
            else:
                orphans.append(src)
    return moves, orphans, empties


def videos_in(directory):
    """Video files sitting directly in this folder, not the ones deeper in."""
    try:
        return [p for p in Path(directory).iterdir()
                if p.is_file() and p.suffix.lower() in VIDEO]
    except OSError:
        return []


def looks_like_its_own_work(folder):
    """A folder a scanner is meant to read as one item: it carries its own
    identity, which for these libraries means a year in the name or a file named
    after the folder. `IMAX` or `Extras` carrying a file carries neither."""
    if YEAR.search(folder.name):
        return True
    name = normalise(folder.name)
    return bool(name) and any(normalise(v.stem).startswith(name) for v in videos_in(folder))


def plan_nested():
    """A movie folder that landed inside another movie's folder.

    It happens with one dragged folder, and a scanner still finds the film, so
    it can sit unnoticed for years while the library's top level lies about what
    it holds. Worse, it hides the filed copy from every check that reads the
    library at its top -- which is how `movies/Pulp Fiction` looked like the only
    copy of that film when the 8.8 GB one was two levels down inside
    `The Godfather (1972)`.

    Only the accidental-nesting signature qualifies: the folder holds its own
    feature-length video, its parent holds one too, and the two are clearly
    different works. A collection box is never a candidate, because its parent
    is the library root and holds no video of its own.
    """
    found = []
    for library in (_config.MOVIES, _config.SERIES):
        lib = Path(library)
        if not lib.is_dir():
            continue
        for dirpath, dirnames, _ in os.walk(lib):
            here = Path(dirpath)
            if here == lib:
                continue
            parent = here.parent
            if parent == lib or not videos_in(parent) or not videos_in(here):
                continue
            if here.name.lower() in EXTRAS or NUMERIC_PART.match(here.name):
                continue
            mine, theirs = normalise(here.name), normalise(parent.name)
            if mine and (mine in theirs or theirs in mine):
                continue        # an edition, or this same film in pieces
            if not looks_like_its_own_work(here):
                continue
            if max(v.stat().st_size for v in videos_in(here)) < FEATURE_BYTES:
                continue        # a clip or a trailer, not a work
            found.append((lib, here, parent))
    # hoisting a folder hoists what is under it, so an inner candidate whose
    # outer one is already planned would move a path that no longer exists
    planned = []
    for lib, here, parent in found:
        if any(other in here.parents for _, other, _ in planned):
            continue        # its outer folder is being hoisted and takes it along
        planned.append((lib, here, parent))
    return [(here, Path(lib) / here.name,
             "filed inside %s; a top-level entry is where a scanner reads it"
             % parent.name)
            for lib, here, parent in planned]


# ---------------------------------------------------------------------- main
def run(pass_name):
    if pass_name == "sanderson-sidecars":
        moves, parked, husks = plan_sanderson(_config.SANDERSON_LOG)
        total = report(pass_name, moves, "their book folders, plus " + _config.PRESERVED_AUDIOBOOKS)
        for path in parked:
            print("       no book attributable, archived instead of guessed: %s" % path)
        for path in husks:
            print("       old tree, emptied by this pass: %s" % path)
        return moves, total, husks
    if pass_name == "music-sidecars":
        moves = plan_music()
        return moves, report(pass_name, moves, _config.PRESERVED_MUSIC), ()
    if pass_name == "mini-stage":
        moves = plan_mini_stage()
        return moves, report(pass_name, moves, _config.PRESERVED_MINI), ()
    if pass_name == "nested-movies":
        moves = plan_nested()
        return moves, report(pass_name, moves, "the library root, beside its own film"), ()
    moves, orphans, empties = plan_video()
    total = report(pass_name, moves, _config.PRESERVED)
    for path in orphans:
        print("       no filed twin, left alone: %s" % path)
    for path in empties:
        print("       emptied by this pass: %s" % path)
    return moves, total, empties


def apply_pass(pass_name, moves, empties=(), prune=False):
    results = relocate(moves, pass_name=pass_name)
    groups = {}
    for record in results:
        root = archive_of(record["dst"])
        if root is not None:
            groups.setdefault(root, []).append(record)
    for preserved, subset in groups.items():
        write_index(preserved, "%s, archived from the libraries" % pass_name, subset)
    print("    applied: %d moved, %.1f MB%s"
          % (len(results), sum(r["bytes"] for r in results) / 1e6,
             "" if not groups else " (indexed in %d preserved tree(s))" % len(groups)))
    if prune and empties:
        removed = prune_empty(empties)
        print("    pruned %d empty director%s"
              % (len(removed), "y" if len(removed) == 1 else "ies"))
        for path in removed:
            print("       %s" % path)


def undo(passes):
    """Move everything this tool archived back to where it came from. Refuses a
    file whose archive copy is gone or whose original path is occupied again."""
    if not AUDIT.is_file():
        print("no audit trail at %s" % AUDIT, file=sys.stderr)
        return 1
    wanted = set(passes) or set(PASSES)
    restore = []
    for line in reversed(AUDIT.read_text().splitlines()):
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("ev") != "move" or rec.get("pass") not in wanted:
            continue
        src, dst = Path(rec["src"]), Path(rec["dst"])
        if not dst.exists():
            print("    refusing, archive copy missing: %s" % dst)
            continue
        if src.exists():
            print("    refusing, original path occupied again: %s" % src)
            continue
        restore.append((dst, src, "restored by --undo"))
    print("undo: %d files back" % len(restore))
    if restore:
        moved = relocate(restore, event="restore")
        print("    restored %d files, %.1f MB"
              % (len(moved), sum(r["bytes"] for r in moved) / 1e6))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Move library litter out of the libraries. Never deletes; "
                    "plans unless --apply.")
    ap.add_argument("passes", nargs="*", choices=list(PASSES) + ["all"],
                    help="which pass(es); default is all")
    ap.add_argument("--apply", action="store_true", help="actually move")
    ap.add_argument("--undo", action="store_true",
                    help="replay this tool's audit backwards for the named pass(es)")
    ap.add_argument("--prune-empty", action="store_true",
                    help="also remove the directories this pass emptied (rmdir only)")
    args = ap.parse_args(argv)          # before any pass: importing this file must
                                        # never start a sweep of the libraries

    if args.undo:
        return undo(args.passes)

    chosen = PASSES if not args.passes or "all" in args.passes else tuple(args.passes)
    grand = 0
    for pass_name in chosen:
        moves, total, empties = run(pass_name)
        grand += total
        if args.apply and moves:
            apply_pass(pass_name, moves, empties, prune=args.prune_empty)
        elif args.apply and args.prune_empty and empties:
            for path in prune_empty(empties):
                print("       pruned %s" % path)
        elif moves:
            print("    plan only -- pass --apply to move %d planned item(s)" % len(moves))
    print("\ntotal %.2f GB across %d pass(es)%s"
          % (grand / 1e9, len(chosen), "" if args.apply else "  (planned; nothing moved)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
