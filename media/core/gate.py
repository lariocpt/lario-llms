#!/usr/bin/env python3
"""Everything that is checked *before* a byte moves, and the reasons it refuses.

PLAN §3.2.1 is the list; this is that list as code, in one place, so the two
surfaces (the driver and the MCP wrapper beside it) cannot disagree about what is
allowed. The order is deliberate: a refusal that costs a microsecond should come
before one that walks a tree.

The exit codes are part of the contract (§4.6) and the reason text matters more
than the code -- "exit 2" is useless, "refused: /mnt/a is inside --dest /mnt/a/out,
re-run with --allow-nested <why>" is actionable.
"""
import errno
import os
import shutil
import time
import uuid

from core import config, names

# §4.6 / §4.1. Kept here so run.py, the tests and the MCP wrapper agree.
EXIT_OK = 0
EXIT_CRASH = 1
EXIT_REFUSE = 2          # bad argument combination, missing dependency, floor
EXIT_LOCKED = 3          # another run holds this pass's lock
EXIT_REVERSED = 10       # core/ imported a domain module (§4.4)

# What each medium means, and where it belongs when --dest is not named.
# `docs` is deliberately absent: it is a pass belonging to `photos` (§2.1), so
# naming it as a medium would let a document end up in a tree of its own that
# nothing else treats as a library.
MEDIUMS = ('photos', 'movies', 'music', 'audiobooks', 'books')


class Refusal(Exception):
    """A refusal to proceed. Carries the fix, not just the complaint."""

    def __init__(self, message, exit_code=EXIT_REFUSE):
        super().__init__(message)
        self.exit_code = exit_code


def dest_for(medium):
    """The library this medium belongs to, unless --dest names somewhere else.

    The environment seam is `LARIO_DEST_<MEDIUM>` so a rehearsal can point the
    whole run at a scratch tree without editing config, and a drive can be built
    by naming `--dest` explicitly. Explicit --dest always wins over this.
    """
    if medium not in MEDIUMS:
        raise Refusal(f'unknown medium {medium!r}; choose one of {", ".join(MEDIUMS)}')
    override = os.environ.get(f'LARIO_DEST_{medium.upper()}'.replace('-', '_'))
    if override:
        return os.path.realpath(override)
    return {
        'photos': config.PHOTO_LIB,
        'movies': config.MOVIES,
        'music': config.MUSIC_LIB,
        'audiobooks': config.AUDIOBOOKS,
        'books': config.BOOKS,
    }[medium]


def extensions_for(medium):
    """Which suffixes are this medium's files. Anything else is foreign (§1.3)."""
    return {
        'photos': config.PHOTO_EXTS,
        'movies': config.MOVIE_EXTS,
        # Audiobooks and books share the bookish sets: an .epub found in an
        # audiobook box is content, not junk, and is filed by the same shape.
        'music': config.AUDIO_EXTS,
        'audiobooks': config.AUDIO_EXTS | config.DOC_EXTS,
        'books': config.DOC_EXTS,
    }[medium]


def other_types(medium):
    """The extension sets of every *other* medium, for the foreign-file report."""
    return {other: extensions_for(other) for other in MEDIUMS if other != medium}


# What each medium needs on PATH or importable, and what to do about it. A missing
# dependency is a refusal with the install command, never a silently-skipped phase
# (§3.2.1): "tags: 812 files skipped" is not a result, it is a swallowed failure.
REQUIRES = {
    'photos': {'exiftool': 'extra/exiftool_pkg/extract_and_install.sh'},
    'movies': {'ffprobe': 'system package ffmpeg', 'ffmpeg': 'system package ffmpeg'},
    # mutagen is a python module, not a command, so it is checked by import below;
    # listing it here too would report the same missing thing twice under two names.
    'music': {},
    'audiobooks': {'ffprobe': 'system package ffmpeg'},
    'books': {},
}


def missing_dependencies(medium):
    """Human-readable install hints for what this medium needs and lacks."""
    missing = []
    for tool, howto in REQUIRES.get(medium, {}).items():
        if shutil.which(tool):
            continue
        missing.append(f'{tool} (install: {howto})')
    if medium == 'music':
        try:
            import mutagen                      # noqa: F401
        except ImportError:
            # Named for THIS machine, because the first hint was written for an
            # imaginary one: `python3 -m venv .venv && .venv/bin/pip install -r
            # requirements.txt` had no pip, no venv module, and no
            # requirements.txt behind it. Python libraries here are pacman
            # packages (rich is python-rich, Pillow is python-pillow), and
            # python-mutagen 1.48.1 is in extra, so that is the one command.
            # The pip form stays as the fallback for a machine that has pip,
            # because a hint that only works in one place is a hint that lies.
            missing.append('python package mutagen (install: sudo pacman -S python-mutagen; '
                           'or pip install mutagen==1.48.1 in whatever environment runs these '
                           'scripts -- it must be importable by the interpreter running '
                           'run.py, not by one it never calls)')
    return missing


def validate_argv(argv):
    """§3.2.1: a path containing a newline or NUL refuses the whole invocation.

    Checked here, before argparse or any script can see it, because the attack is
    a filename that breaks a log line or a shell quote -- and a path like that is
    indistinguishable from an injection attempt at the boundary that matters.
    """
    for arg in argv:
        if '\x00' in arg or '\n' in arg or '\r' in arg:
            raise Refusal(f'refused: argument {arg!r} contains a newline or NUL. '
                          f'No run is possible with an argument like that')


def new_run_id(medium, verb):
    """Sortable, unique, and legible in a log line without decoding anything.

    Sortable means *chronologically* sortable, and the naive version was not: a
    second-resolution timestamp with a random hex tail makes two runs started in
    the same second order by their random part, so `ls _mediatool | tail -1` --
    how an operator finds "the run I just did" -- picked arbitrarily. The
    microsecond is what restores the ordering; the random tail stays only to
    separate two processes that collide inside the same microsecond.
    """
    now = time.time()
    return (f'{verb}-{medium}-' + time.strftime('%Y%m%dT%H%M%S', time.gmtime(now)) +
            f'{int((now % 1) * 1_000_000):06d}-{uuid.uuid4().hex[:4]}')


def evidence_dir(dest, run_id):
    """`<dest>/_mediatool/<run_id>` -- §4.3.4, on the same filesystem as the data.

    Created here so the caller can write into it immediately; `dest` itself is
    created only by `prepare_destination`, never implicitly by this function.
    """
    return os.path.join(dest, '_mediatool', run_id)


def claim_run_dir(dest, medium, verb):
    """Mint a run id *and* atomically claim its evidence directory.

    Uniqueness cannot come from the clock. `time.time()` repeats within a
    microsecond on this machine -- measured, not guessed -- so a timestamp-based
    id is only ever *ordered*, never unique. The test that asserted otherwise
    failed about five times in ten, which is the correct answer from a test: the
    property asked for was not the property that holds.

    So ordering comes from the timestamp (chronological `ls`, and an operator
    finding "the run I just did" with `tail -1` is the whole point of the layout)
    and uniqueness comes from creating the directory, because the filesystem is
    the only thing here that can say *that name is taken*. Two runs that collide
    on an id would otherwise share an evidence directory, and one run's manifest
    quietly becoming another's is exactly the sort of thing this toolkit refuses
    to leave to chance.
    """
    for _ in range(200):
        run_id = new_run_id(medium, verb)
        path = evidence_dir(dest, run_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            os.mkdir(path)                       # no exist_ok: the claim is the point
        except FileExistsError:
            continue
        return run_id, path
    raise Refusal(f'refused: could not claim a free run directory under '
                  f'{os.path.join(dest, "_mediatool")} after 200 attempts')


def fstype(path):
    """The filesystem holding `path`, from the longest matching mount point.

    Reading `/proc/mounts` rather than calling `statvfs` because `statvfs` cannot
    tell exFAT from ext4, and the distinction decides whether a trailing dot, a
    colon, or a case-only difference is a real hazard (§17.7).
    """
    try:
        with open('/proc/mounts', encoding='utf-8') as handle:
            lines = handle.read().splitlines()
    except OSError:
        return 'unknown'
    target = os.path.realpath(path)
    best, best_type = '', 'unknown'
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        point, kind = fields[1], fields[2]
        if kind == 'autofs':
            continue
        if target == point or target.startswith(point.rstrip('/') + os.sep):
            if len(point) > len(best):
                best, best_type = point, kind
    return best_type


CASE_FOLDING = ('exfat', 'vfat', 'msdos', 'ntfs', 'ntfs3', 'fuse.ntfs-3g', 'fuse.exfat')


def case_folds(fstype_value):
    """Whether `Foo.mkv` and `foo.mkv` are the same file on this filesystem."""
    return fstype_value in CASE_FOLDING


def free_bytes(path):
    return shutil.disk_usage(path).free


def check_floor(dest, needed, floor_bytes):
    """§3.2.1: refuse before the first write if the run would fill the destination.

    Checked against the *plan's* predicted net growth, not a guess, so the number
    the owner reviewed is the number that was checked.
    """
    free = free_bytes(dest)
    if free - needed < floor_bytes:
        raise Refusal(
            f'refused: {dest} has {free / 1e9:.1f} GB free and this run needs '
            f'{needed / 1e9:.1f} GB plus a {floor_bytes / 1e9:.1f} GB floor. Free space '
            f'first, or point --dest at a larger volume')
    return free


def check_paths(dest, srcs, allow_nested=False, allow_reason=''):
    """§3.2.1 and §13.2/§13.3: shape of the argument set, before touching files.

    One destination, sources that exist, and no nesting without a recorded
    reason -- a run whose destination sits inside one of its own sources will, on
    the second pass, feed its own output back as input. That is how a consolidation
    job duplicates a library, so nesting is a refusal rather than a warning, and
    the reason for allowing it is kept in the plan as the thing the owner asserted.
    """
    if not srcs:
        raise Refusal('refused: at least one --src is required')
    if not os.path.isdir(dest):
        raise Refusal(f'refused: --dest {dest} is not a directory. Create it first, or '
                      f'pass the volume that holds it')
    if not os.access(dest, os.W_OK):
        raise Refusal(f'refused: --dest {dest} is not writable by this user')

    real_dest = os.path.realpath(dest)
    real_srcs = []
    for src in srcs:
        if not os.path.exists(src):
            raise Refusal(f'refused: --src {src} does not exist')
        if not os.path.isdir(src):
            raise Refusal(f'refused: --src {src} is not a directory. This toolkit moves '
                          f'collections; copy a single file by hand')
        real = os.path.realpath(src)
        if real == real_dest:
            raise Refusal(f'refused: --src {src} IS --dest {dest}: a run cannot read and '
                          f'write the same tree')
        nested = []
        if real.startswith(real_dest + os.sep):
            nested.append(f'--src {src} is inside --dest {dest}')
        elif real_dest.startswith(real + os.sep):
            nested.append(f'--dest {dest} is inside --src {src}')
        for other in real_srcs:
            if real.startswith(other + os.sep) or other.startswith(real + os.sep):
                nested.append(f'--src {src} is nested inside another --src')
        if nested and not (allow_nested and allow_reason):
            raise Refusal(
                f'refused: {"; ".join(nested)}. That lets a second pass read what the '
                f'first one wrote. If it really is intended, re-run with '
                f'--allow-nested "<why>" and the reason goes in the plan')
        real_srcs.append(real)
    return real_dest, real_srcs


def probe_writable(dest, run_dir):
    """Prove the destination accepts writes *and* names, and record what it is.

    The probe file is kept rather than deleted: it is evidence, and the toolkit
    does not delete what it did not create through the ledger. It also means the
    first write to a new volume happens before any content has been committed to
    a plan, which is the cheapest possible moment to discover a read-only mount.
    """
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, 'fs-probe.txt')
    value = free_bytes(dest)
    kind = fstype(dest)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(f'dest={dest}\nfstype={kind}\ncase_folding={case_folds(kind)}\n'
                     f'free_bytes={value}\nchecked_utc={time.time()}\n')
        handle.flush()
        os.fsync(handle.fileno())
    return {'path': path, 'fstype': kind, 'case_folding': case_folds(kind),
            'free_bytes': value}


def plan_dest_dir(dest, medium):
    """Where this medium's files land under `dest` -- always its own subtree.

    §15.3: one subtree per type, so a drive that ends up half-processed is still
    legible and a later pass can be pointed at one subtree without the others.
    """
    return os.path.join(dest, {'photos': 'Photos', 'movies': 'Movies', 'music': 'Music',
                               'audiobooks': 'Audiobooks', 'books': 'Books'}[medium])


def is_media(path, medium):
    """Whether this path is a file of `medium`'s type (suffix, nothing clever).

    Clutter is excluded here rather than left to the walker, because the
    AppleDouble fork of `IMG_0001.jpg` is named `._IMG_0001.jpg` and *does* match
    the photo suffix set -- counting that as media would file a 4 KB resource fork
    into the library and make every byte total in the summary a lie (§1.3).
    """
    if names.is_clutter(path):
        return False
    return os.path.splitext(path)[1].lower() in extensions_for(medium)


def foreign(path, medium):
    """The medium this *other* type's file belongs to, or None.

    §1.3: a foreign file is reported with the command that owns it, and moved by
    nothing. Returning the owner rather than just "no" is what lets the report
    print a runnable line instead of a shrug.
    """
    leaf = os.path.splitext(path)[1].lower()
    for other, exts in other_types(medium).items():
        if leaf in exts:
            return other
    return None


def ensure_EROFS(exc):
    """A short, honest line for the one filesystem error that confuses people."""
    if isinstance(exc, OSError) and exc.errno in (errno.EROFS, errno.EACCES):
        return f'{exc.strerror} -- is the volume mounted read-only?'
    return str(exc)
