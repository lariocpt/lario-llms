#!/usr/bin/env python3
"""Names a run is allowed to produce, and the proof that it produces nothing else.

Three problems live here and conflating them is how a consolidation job loses a
file to a silent overwrite:

* **collision** -- two inputs, one target name. Resolved deterministically and
  never by overwriting (`d54fc1a`'s encoder refuses the same thing with
  `dup_stem`; this is that rule for every type).
* **escape** -- a name that resolves outside the root it was meant to land in
  (`..`, an absolute path, or a symlink pointed somewhere else).
* **representability** -- a name that survives on XFS and cannot be written on
  exFAT, which is the filesystem most external drives arrive with: `: * ? " | < >`
  are illegal, a trailing dot or space is dropped by Windows, the 22 reserved
  device names are unwritable, more than 255 UTF-16 code units is truncated, and
  a filesystem that folds case cannot tell `foo.MOV` from `foo.mov`.

Note what is *not* a limitation, because the plan used to claim it: exFAT has no
4 GiB file limit (that is FAT32). Its real limits are the ones above.

This module is a library (unlike the domain corpora beside it) and deletes
nothing.
"""
import os
import re
import unicodedata

# What exFAT/NTFS refuse outright. Kept as a string so the reason text can name
# the exact character that was dropped.
ILLEGAL = ':*?"|<>'
# Control characters and the DEL, which no filesystem is happy about.
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
# Reserved by Windows regardless of extension. COM0/LPT0 are not reserved, so
# they are deliberately absent: inventing rules here would rename files that
# needed no renaming.
_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}
# exFAT's per-component limit, counted in UTF-16 code units -- Python counts
# code points, so a non-BMP character (an emoji) is two units here.
EXFAT_MAX_COMPONENT = 255
# Clutter that is neither a media file nor a foreign media file: counted, left
# alone, and excluded from every byte total so it cannot make a reclaim number
# look better than it is (PLAN §1.3).
CLUTTER_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '@eaDir', '.stfolder',
                 'Spotlight-V100', '.Spotlight-V100', '.Trashes', '.Trash-1000',
                 'fseventsd', '.fseventsd', '@Recycle.Bin', '$RECYCLE.BIN',
                 '.directory', 'lost+found'}
CLUTTER_PREFIXES = ('._',)          # AppleDouble resource forks
CLUTTER_SUFFIXES = ('.tmp', '.part', '.crdownload', '.partial')


def is_clutter(path):
    """True for the junk a consolidation must neither move nor count.

    Directories are matched by their own name (`@eaDir` and friends), which is
    how a whole subtree is skipped without walking into it.
    """
    base = os.path.basename(path.rstrip(os.sep))
    if base in CLUTTER_NAMES:
        return True
    if base.startswith(CLUTTER_PREFIXES):
        return True
    if base.lower().endswith(CLUTTER_SUFFIXES):
        return True
    return False


def utf16_len(text):
    """Length in UTF-16 code units, which is what exFAT counts."""
    return len(text.encode('utf-16-le')) // 2


def exfat_problems(name):
    """Reasons this name cannot be written on exFAT -- empty means it can.

    Diagnostics, not a mutation: the caller decides whether to sanitise or to
    refuse, and a report that says *why* a name changed is reviewable while a
    silent change is not.
    """
    bad = []
    if not name:
        bad.append('empty name')
    if _CONTROL.search(name):
        bad.append('control character')
    for ch in ILLEGAL:
        if ch in name:
            bad.append(f'illegal character {ch!r}')
    if '\x00' in name or '\n' in name:
        bad.append('newline or NUL')
    stem, slash, tail = name.rpartition(os.sep)
    if tail != tail.rstrip('. '):
        bad.append('trailing dot or space')
    if utf16_len(name) > EXFAT_MAX_COMPONENT:
        bad.append(f'{utf16_len(name)} UTF-16 units exceeds {EXFAT_MAX_COMPONENT}')
    if name.split('.')[0].upper() in _RESERVED:
        bad.append(f'reserved Windows device name {name.split(".")[0].upper()}')
    return bad


def sanitise(name, replacement='_'):
    """An exFAT-representable version of `name`, preserving as much as possible.

    Unicode is *kept*, not transliterated: Arabic and Urdu filenames are the
    content, not a problem to clean away. NFKC-normalises so two visually
    identical names on a case-insensitive target do not become two entries the
    owner cannot tell apart -- and so the collision check in `unique` sees them
    as the collision it is.
    """
    name = os.path.basename(str(name).replace('\x00', ''))
    name = unicodedata.normalize('NFKC', name)
    name = _CONTROL.sub(replacement, name)
    for ch in ILLEGAL:
        name = name.replace(ch, replacement)
    stem, dot, ext = name.rpartition('.')
    if dot and stem:
        # Truncate the stem, never the extension: `.jpg` cut to `.jp` stops being a
        # JPEG, and a file nobody's tool can open is worse than one whose name lost
        # a suffix. Counted in UTF-16 units, because that is what exFAT counts --
        # cutting on code points would let an emoji push the name back over.
        room = EXFAT_MAX_COMPONENT - utf16_len(ext) - 1
        head = stem.encode('utf-16-le')[:max(2, room * 2)].decode('utf-16-le', 'ignore')
        name = head.rstrip('. ') + dot + ext
    else:
        name = name[:EXFAT_MAX_COMPONENT].rstrip('. ')
    if name.split('.')[0].upper() in _RESERVED:
        name = '_' + name
    if not name or name in ('.', '..'):
        name = f'{replacement}unnamed'
    return name


def key(name):
    """The identity of a name on a case-insensitive filesystem.

    Comparing raw strings is the bug: on exFAT and NTFS `Foo.mov` and `foo.mov`
    are the *same file*, so a dedupe that treats them as different will write one
    over the other without noticing.
    """
    return unicodedata.normalize('NFKC', name).casefold()


def unique(seen, name):
    """A name not already claimed in this directory, deterministically.

    `seen` maps `key()` -> the name that claimed it, and is updated. The suffix
    goes before the extension (`Title (2).mkv`, not `Title.mkv (2)`), because a
    media file whose extension is no longer what its container is confuses every
    player and every probe downstream.

    No counter is ever skipped and no random suffix is used: two runs over the
    same input produce the same names, which is what makes a plan reviewable and
    a re-run resumable.
    """
    candidate = sanitise(name)
    stem, dot, ext = candidate.rpartition('.')
    if not dot or not stem:                     # no extension, or a dotfile
        stem, ext, dot = candidate, '', ''
    base, n = candidate, 2
    while key(base) in seen:
        mid = f' ({n})'
        room = EXFAT_MAX_COMPONENT - utf16_len(ext) - utf16_len(mid) - (1 if dot else 0)
        base = stem[:max(1, room)] + mid + dot + ext
        n += 1
        if n > 10_000:                           # a directory that cannot be named
            raise RuntimeError(f'no unique name available for {name!r} in a full directory')
    seen[key(base)] = candidate
    return base


def within(root, path):
    """True when `path` cannot escape `root`.

    Both sides are resolved first: a symlink inside the root that points outside
    it is an escape, and so is `..` in an unresolved string. `os.path.relpath`
    is not used because it happily reports a sibling tree as `../other`.
    """
    root = os.path.realpath(root)
    target = os.path.realpath(path)
    if target == root:
        return True
    return target.startswith(root + os.sep)


def relpath_under(root, path):
    """The path of `path` under `root`, or None when it is not under it."""
    root = os.path.realpath(root)
    target = os.path.realpath(path)
    if target == root:
        return ''
    if not target.startswith(root + os.sep):
        return None
    return os.path.relpath(target, root)
