"""Inventory the staged mini-mobile copy: tags, audio properties, AND the

path-derived reading of each file, so the two can be compared instead of
trusting either one blindly (these packs have tags containing filenames)."""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_meta.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import os
import re
import sys
import json
import collections

import mutagen
from mutagen.id3 import ID3

from paths import STAGE
AUDIO = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aiff", ".wma"}

# a directory like "CD 1" / "Disc 2" / "cd1"
DISC_RE = re.compile(r"^\s*(cd|disc)\s*\.?\s*(\d{1,2})\s*$", re.I)
# leading track numbers in a filename: "01 - Title", "01. Title", "01-06 Title"
NUM_RE = re.compile(r"^(\d{1,2})(?:[\s\-._]+(\d{1,2}))?[\s\-._]+")


def id3_get(tags, *keys):
    for k in keys:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def read_one(path):
    """Tags + probe facts for one file."""
    out = {"error": ""}
    try:
        m = mutagen.File(path)
    except Exception as e:
        out["error"] = f"mutagen: {type(e).__name__}: {e}"
        return out
    if m is None:
        out["error"] = "mutagen: unsupported format"
        return out
    info = m.info
    out["dur"] = round(float(info.length or 0), 3)
    out["br"] = int((info.bitrate or 0) // 1000)
    out["sr"] = int(info.sample_rate or 0)
    out["ch"] = int(getattr(info, "channels", 0) or 0)
    out["fmt"] = type(m).__name__
    tags = m.tags
    if tags is None:
        return out
    # works for both ID3 (keys) and MP4/other (dict-ish names)
    if isinstance(tags, dict) and all(isinstance(k, str) for k in tags):
        try:
            got = ID3(path, ID3.NO_RIFF)
        except Exception:
            got = None
        if got is not None:
            tags = got
    out["tpe1"] = id3_get(tags, "TPE1", "TPE2")
    out["tpe2"] = id3_get(tags, "TPE2")
    out["talb"] = id3_get(tags, "TALB")
    out["tit2"] = id3_get(tags, "TIT2")
    out["trck"] = id3_get(tags, "TRCK")
    out["tpos"] = id3_get(tags, "TPOS")
    out["year"] = id3_get(tags, "TDRC", "TYER", "TORY")
    out["genre"] = id3_get(tags, "TCON")
    return out


def parse_path(rel):
    """Read the same track out of the directory structure + filename."""
    parts = rel.split(os.sep)
    pack = parts[0]
    dirs = parts[1:-1]
    stem = os.path.splitext(parts[-1])[0]

    disc = 0
    album_dirs = list(dirs)
    if album_dirs and DISC_RE.match(album_dirs[-1]):
        disc = int(DISC_RE.match(album_dirs[-1]).group(2))
        album_dirs = album_dirs[:-1]
    # ancestor dirs are useful context ("Live Albums", "Singles"); only dirs made
    # entirely of separator punctuation are dropped ("-------Live Albums---" is kept,
    # its label stripped, but "-" alone is nothing).
    groups = []
    for d in album_dirs[:-1]:
        label = d.strip("-_ .")
        if not label and set(d.strip()) <= set("-_ ."):
            continue
        groups.append(label or d)
    album_folder = album_dirs[-1] if album_dirs else ""

    # filename track number(s)
    track = 0
    title = stem.strip()
    mm = NUM_RE.match(title)
    if mm:
        a, b = mm.group(1), mm.group(2)
        title = title[mm.end():].strip()
        track = int(b if b else a)
    return {
        "pack": pack,
        "groups": groups,
        "album_folder": album_folder,
        "disc": disc,
        "ftrack": track,
        "ftitle": title,
        "stem": stem,
    }


def main():
    rows = []
    errs = []
    for root, dirs, files in os.walk(STAGE, onerror=lambda e: errs.append(str(e))):
        for f in sorted(files):
            p = os.path.join(root, f)
            if os.path.islink(p):
                continue
            if os.path.splitext(f)[1].lower() not in AUDIO:
                continue
            rel = os.path.relpath(p, STAGE)
            r = {"rel": rel, "bytes": os.path.getsize(p)}
            r.update(parse_path(rel))
            r.update(read_one(p))
            rows.append(r)
    print(f"   audio files: {len(rows)}   walk errors: {len(errs)}", file=sys.stderr)
    with open("/home/lario/music-reorganize/mini-meta.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # --- evidence report: can the tags be trusted here? ---
    tag_title_is_filename = 0
    no_tag_title = 0
    tag_matches_path_title = 0
    tag_differs_from_path = []
    for r in rows:
        t = r.get("tit2", "")
        st = r["stem"]
        if not t:
            no_tag_title += 1
        elif t.lower().endswith((".mp3", ".flac", ".m4a")) or t == st:
            tag_title_is_filename += 1
        elif t.strip().lower() == r["ftitle"].strip().lower():
            tag_matches_path_title += 1
        else:
            tag_differs_from_path.append(r)
    print(f"\n=== TIT2 vs filename ===", file=sys.stderr)
    print(f"   tag == path title           : {tag_matches_path_title}", file=sys.stderr)
    print(f"   tag is the filename itself  : {tag_title_is_filename}", file=sys.stderr)
    print(f"   no title tag at all         : {no_tag_title}", file=sys.stderr)
    print(f"   tag differs from path title : {len(tag_differs_from_path)}", file=sys.stderr)

    print(f"\n=== albums: TALB vs folder ===", file=sys.stderr)
    same = diff = 0
    for r in rows:
        if r.get("talb", "").strip().lower() == r["album_folder"].strip().lower():
            same += 1
        else:
            diff += 1
    print(f"   TALB == folder name : {same}", file=sys.stderr)
    print(f"   differs             : {diff}", file=sys.stderr)

    print(f"\n=== per pack ===", file=sys.stderr)
    for pack, c in collections.Counter(r["pack"] for r in rows).items():
        print(f"   {c:4d}  {pack}", file=sys.stderr)

    print(f"\n=== audio formats ===", file=sys.stderr)
    for k, c in collections.Counter(
        (r["fmt"], r["br"], r["sr"]) for r in rows
    ).most_common(12):
        print(f"   {c:4d}  {k}", file=sys.stderr)

    print(f"\n=== files with no usable title from either source ===", file=sys.stderr)
    bad = [r for r in rows if not r.get("tit2") and not r["ftitle"]]
    print(f"   {len(bad)}", file=sys.stderr)

    print(f"\n=== 6 tag/path mismatches ===", file=sys.stderr)
    for r in tag_differs_from_path[:6]:
        print(f"   {r['rel'][:60]}\n      TIT2={r['tit2']!r}  path={r['ftitle']!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
