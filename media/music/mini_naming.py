"""Filing + tag rules for imported files (same rules used in the earlier phases).

Folder layout:   Artist/Album (YYYY)/NN - Title.ext
                 Artist/Album (YYYY)/Disc N/NN - Title.ext   (only when 2+ discs)
albumartist      must equal the artist folder it is filed under
TPE1             full credit line (may differ from albumartist)
Various Artists  only when an album's tracks really name different artists

Tag writes never overwrite a genuine value: they fill gaps. Writes go through
copy -> tag -> read-back -> os.replace, so a file is never left half-written.
"""
import os
import re

# how the library already spells these artists (the source pack misspells one)
ARTIST_CANON = {
    "led zepplin": "Led Zeppelin",
    "led zeppelin": "Led Zeppelin",
    "led zeppelin i": "Led Zeppelin",
    "busta rhymes": "Busta Rhymes",
    "eek-a-mouse": "Eek-A-Mouse",
    "eek a mouse": "Eek-A-Mouse",
    "eek-mouse": "Eek-A-Mouse",
    "the crystal method": "The Crystal Method",
    "crystal method": "The Crystal Method",
    "crystal_method": "The Crystal Method",
}

RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} \
    | {f"LPT{i}" for i in range(1, 10)}

_JUNK_TITLE = re.compile(r"^\s*(track|titre|song|piste)[\s\-_.]*\d+\s*$", re.I)


def clean_text(value, for_fs=False, cap=200):
    """Library cleaning rules: no control characters, no filesystem-hostile
    punctuation, one space between words, nothing Windows rejects."""
    s = (value or "").strip()
    if not s:
        return ""
    s = "".join(ch for ch in s if ch >= " " or ch in "\t")
    s = re.sub(r"[\r\n\t]+", " ", s)
    if for_fs:
        s = s.replace("/", "-").replace("\\", "-")
    s = re.sub(r'[<>:"|?*]', "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(". ")  # Windows: no trailing dots or spaces
    if s.upper() in RESERVED:
        s = "_" + s
    while s.endswith((" ", ".")):
        s = s[:-1]
    if len(s) > cap:
        s = s[:cap].rstrip(" .")
    return s


def canon_artist(name):
    n = clean_text(name)
    key = re.sub(r"[_\s]+", " ", n).strip().lower()
    return ARTIST_CANON.get(key, n)


YEAR_RE = re.compile(r"(?<!\d)(19[2-9]\d|20[0-2]\d)(?!\d)")
VA_RE = re.compile(r"^\s*(various( artists)?|va)\s*$", re.I)


def year_from(value):
    m = YEAR_RE.search(value or "")
    return int(m.group(1)) if m else 0


def strip_va_prefix(album):
    """'Various - Album' as an album name loses the redundant prefix."""
    return clean_text(re.sub(r"^\s*various\s*[-–—]\s*", "", album or "", flags=re.I))


def album_name(talb, folder, albumartist):
    """Album name for the folder: prefer the tag, fall back to the directory."""
    a = clean_text(talb) or clean_text(re.sub(r"^\(\d{4}\)\s*", "", folder or ""))
    a = strip_va_prefix(a)
    # a folder named "Artist - Album" gives the album half
    if albumartist and a.lower().startswith(albumartist.lower() + " - "):
        a = clean_text(a[len(albumartist) + 3:])
    return a or clean_text(folder) or "[Unknown Album]"


def junk_title(title):
    return (not title) or bool(_JUNK_TITLE.match(title)) \
        or title.lower().endswith((".mp3", ".flac", ".m4a", ".wav"))


def merge_track(trck, ftrack, total=0):
    """Track number: prefer the tag's leading number, else the filename's."""
    m = re.match(r"^\s*(\d{1,3})\s*(?:/\s*\d{1,3})?\s*$", str(trck or ""))
    n = int(m.group(1)) if m else (int(ftrack) if ftrack else 0)
    return n


def target_path(artist, album, year, disc_folder, track, title, ext):
    """disc_folder is 'Disc 1'/'CD 2'/None -- decided by the planner, which
    knows whether the release is multi-disc at all."""
    parts = [clean_text(artist, for_fs=True) or "Unsorted"]
    a = clean_text(album, for_fs=True) or "[Unknown Album]"
    parts.append(f"{a} ({year})" if year else a)
    if disc_folder:
        parts.append(clean_text(disc_folder, for_fs=True))
    t = clean_text(title, for_fs=True) or "untitled"
    name = f"{track:02d} - {t}" if track else t
    parts.append(name + (ext if ext.startswith(".") else f".{ext}"))
    return os.path.join(*parts)


def fill_plan(tags, existing):
    """Which tag fields may be written: only gaps.

    `tags` is what we would write, `existing` what the file already carries.
    A value that exists is never replaced, so a real title is safe from a
    filename-derived guess.
    """
    out = {}
    for k, v in tags.items():
        if v in (None, "", 0):
            continue
        cur = existing.get(k)
        if cur not in (None, "", 0):
            continue
        out[k] = v
    return out
