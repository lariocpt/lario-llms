"""Move the staged mini-mobile audio into the library, minus what is already

there and minus what no player can open.

Filing follows the library's own rules (Artist/Album (YYYY)/[Disc N/]NN - Title)
using the naming helpers in mini_naming.py. An existing library file is NEVER
overwritten: a collision on the same bytes is a skip, a collision on different
bytes goes beside it with a marker.

Writes go through a temporary file in the destination directory, tags filled
into gaps there, read back, then os.replace -- so a half-written file never
appears at the final path. Tag writes fill gaps only: a genuine title, artist
or album is never replaced. A title tag that is literally a filename is not a
genuine value, so it is treated as a gap.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_import.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import hashlib
import json
import os
import re
import shutil
import sys
import time

from mutagen import File as MFile
from mutagen.id3 import ID3NoHeaderError

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mini_naming as N

from paths import STAGE
from paths import LIB
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
os.makedirs(WORK, exist_ok=True)   # one evidence root for the whole pass
VERDICT = f"{WORK}/mini-verdict-final.jsonl"
MD5SRC = f"{WORK}/mini-source-md5.tsv"
PLAN = f"{WORK}/mini-import-plan.jsonl"
from paths import FALLBACK


def md5(path, buf=1 << 22):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tags(path):
    """Tags in easy-style keys, whatever the container."""
    try:
        f = MFile(path, easy=True)
    except Exception:
        return {}
    if not f or not f.tags:
        return {}
    out = {}
    for key in ("title", "artist", "albumartist", "album", "date", "year",
                "tracknumber", "discnumber"):
        try:
            v = f.tags.get(key)
        except Exception:
            v = None
        if v:
            v = str(v[0] if isinstance(v, list) else v).strip()
            if v:
                out[key] = v
    return out


def filename_hint(rel):
    """Track number and title from the path, the last reliable word when the
    tags were written by a release pack."""
    base = os.path.splitext(os.path.basename(rel))[0]
    m = re.match(r"^\s*(?:(\d{1,2})\s*[-_]\s*)?(\d{1,2})\s*[-_]\s*(.+)$", base)
    if m:
        return int(m.group(2)), m.group(3).replace("_", " ").strip()
    m = re.match(r"^\s*(\d{1,3})\s*[-_]\s*(.+)$", base)
    if m:
        return int(m.group(1)), m.group(2).replace("_", " ").strip()
    return 0, base.replace("_", " ").strip()


def folder_hint(rel):
    """The release folder the file sits in, and a disc folder if it has one.
    Scene packs name the album in the directory far more often than in TPE2."""
    parts = os.path.dirname(rel).split(os.sep)
    disc = None
    for p in parts:
        if re.match(r"^\s*(cd|disc|disk)\s*\d", p, re.I):
            disc = p.strip()
    # a "(1999) Artist - Album" or "Artist - Album (1999)" style folder
    album_dir = parts[-1] if parts and parts[-1] not in ("", ".") else ""
    if album_dir and re.match(r"^[\d\s._-]+$", album_dir):
        album_dir = ""
    return album_dir, disc


def fix_group(fields):
    """Repair release-pack tag artifacts across the files of one album.

    A track number that repeats across an album is not a track number, and a
    title that is identical on every track of an album is the album name in
    disguise. The Catastrophic pack tags all 17 files TRCK 1/17 TIT2
    Catastrophe, which filed 17 songs over the top of one another.
    """
    if len(fields) < 2:
        return
    tag_t = [f["tag_trk"] for f in fields]
    if len(set(tag_t)) < len(fields):
        file_t = [f["file_trk"] for f in fields]
        if len(set(file_t)) == len(fields) and all(file_t):
            for f in fields:
                f["track"] = f["file_trk"]
                f["trk_from"] = "filename (the pack tags every track as " \
                                f"{tag_t[0]})"
        else:
            for i, f in enumerate(sorted(fields, key=lambda f: f["rel"]), 1):
                f["track"] = i
                f["trk_from"] = "sequence within the album (no usable number)"
    titles = [f["tag_title"] for f in fields]
    if len(set(t for t in titles if t)) == 1:
        fnames = [f["file_title"] for f in fields]
        if len(set(fnames)) == len(fields):
            for f in fields:
                f["title"] = f["file_title"]
                f["title_from"] = "filename (every track of this album carries " \
                                  f"the same title tag)"


def main():
    dry = "--apply" not in sys.argv
    rows = [json.loads(l) for l in open(VERDICT, encoding="utf-8") if l.strip()]

    # md5 recorded from the mini itself. Two staged files with the same hash
    # are the same file, so the second one must not become a library duplicate
    src_md5 = {}
    for line in open(MD5SRC, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[0] != "DONE":
            src_md5[parts[1]] = parts[0]

    keep = []
    for r in rows:
        if r["verdict"] not in ("NEW", "EXTENDED", "CONFLICT", "UNJUDGED"):
            continue
        if r["verdict"] == "PARK" or r["damaged"] or (r.get("dec_s") or 0) < 1.0:
            continue
        keep.append(r)

    seen_hash = {}
    groups = {}
    dupe_batch, nofile, already = 0, [], 0
    for r in sorted(keep, key=lambda r: r["rel"]):
        sp = os.path.join(STAGE, r["rel"])
        if not os.path.isfile(sp):
            nofile.append(r["rel"])
            continue
        h = src_md5.get(r["rel"]) or md5(sp)
        if h in seen_hash:
            dupe_batch += 1
            continue
        seen_hash[h] = r["rel"]

        tg = read_tags(sp)
        album_dir, disc = folder_hint(r["rel"])
        ftrack, ftitle = filename_hint(r["rel"])

        artist = N.canon_artist(tg.get("albumartist") or tg.get("artist") or "")
        if not artist:
            artist = N.canon_artist(os.path.dirname(r["rel"]).split(os.sep)[0])
        album = N.album_name(tg.get("album"), album_dir, artist)
        if disc:
            # the pack writes the disc into the folder name AND keeps a CD 1
            # subfolder; filing both would give "...(Disc 1) (2003)/CD 1/01 -"
            album = re.sub(r"\s*[(\[]\s*(cd|disc|disk)\s*\d*\s*[)\]]\s*", " ",
                           album, flags=re.I).strip()
        year = N.year_from(tg.get("date") or tg.get("year") or "") \
            or N.year_from(album_dir) or N.year_from(r["rel"])
        tag_title = tg.get("title") or ""
        title = ftitle if N.junk_title(tag_title) else tag_title
        groups.setdefault((artist, album, disc), []).append({
            "rel": r["rel"], "src": sp, "md5": h, "bytes": r["bytes"],
            "verdict": r["verdict"], "artist": artist, "album": album,
            "year": year, "disc": disc, "ext": os.path.splitext(sp)[1].lower()
            or ".mp3", "tag_trk": tg.get("tracknumber") or "", "file_trk": ftrack,
            "track": N.merge_track(tg.get("tracknumber"), ftrack),
            "tag_title": tag_title, "file_title": ftitle, "title": title,
            "tag_artist": tg.get("artist") or artist,
        })

    for fields in groups.values():
        fix_group(fields)

    batch_md5 = {f["md5"] for fields in groups.values() for f in fields}

    # nothing was deleted from the library by this script, so the only files
    # that can be in these folders and are this new are ones this script just
    # wrote. A byte-identical copy standing at the wrong track number is a
    # misfiling by the previous pass, not a user's file
    RECENT = time.time() - 3600

    def misplaced(path):
        """True if this file was written by a pass of this script and its
        bytes belong somewhere else in the batch."""
        try:
            if not os.path.isfile(path) or os.path.getmtime(path) < RECENT:
                return False
        except OSError:
            return False
        return md5(path) in batch_md5

    plan = []
    used = set()
    for fields in groups.values():
        for f in sorted(fields, key=lambda f: (f["track"], f["rel"])):
            if not f["album"]:
                rel = os.path.join(FALLBACK, N.clean_text(f["rel"], for_fs=True))
            else:
                rel = N.target_path(f["artist"], f["album"], f["year"], f["disc"],
                                    f["track"], f["title"], f["ext"])
            dest = os.path.join(LIB, rel)
            # never land on top of something: same bytes is a skip, different
            # bytes goes beside it marked, so no file is ever lost by filing.
            # Our own misplaced copy from a previous pass is not an obstacle
            if os.path.exists(dest) and md5(dest) == f["md5"]:
                # already filed by an earlier pass: record it so the manifest
                # is the complete set, and the deletion audit can check it
                used.add(dest)
                already += 1
                f["dest"], f["lib_rel"] = dest, os.path.relpath(dest, LIB)
                plan.append(f)
                continue
            while dest in used or (os.path.exists(dest) and not misplaced(dest)):
                base, e2 = os.path.splitext(dest)
                m = re.search(r" \((\d+)\)$", base)
                if m:
                    base = base[:m.start()] + f" ({int(m.group(1)) + 1})"
                else:
                    base = f"{base} (2)"
                dest = base + f["ext"]
            used.add(dest)
            f["dest"] = dest
            f["lib_rel"] = os.path.relpath(dest, LIB)
            plan.append(f)

    want_dest = {p["md5"]: p["dest"] for p in plan}

    written = failed = 0
    bytes_in = 0
    for p in plan:
        if dry:
            continue
        try:
            os.makedirs(os.path.dirname(p["dest"]), exist_ok=True)
            if os.path.exists(p["dest"]) and md5(p["dest"]) == p["md5"]:
                continue
            tmp = p["dest"] + ".partial"
            shutil.copy2(p["src"], tmp)
            if os.path.getsize(tmp) != p["bytes"]:
                raise OSError("size mismatch after copy")
            if md5(tmp) != p["md5"]:
                raise OSError("md5 mismatch against the mini's own hash")
            os.replace(tmp, p["dest"])
            written += 1
            bytes_in += p["bytes"]
        except Exception as exc:
            failed += 1
            print(f"      FAIL {p['lib_rel'][:56]:58s} {exc}")
            junk = p["dest"] + ".partial"
            if os.path.exists(junk):
                os.unlink(junk)

    # sweep the folders this import files into for copies the previous pass
    # wrote at the wrong track number: same bytes, wrong name, so the bytes
    # are already safe at their own path and this one is a duplicate
    cleaned = []
    if not dry:
        for d in sorted({os.path.dirname(p["dest"]) for p in plan}):
            try:
                entries = sorted(os.listdir(d))
            except OSError:
                continue
            for name in entries:
                path = os.path.join(d, name)
                if not misplaced(path):
                    continue
                if os.path.abspath(want_dest.get(md5(path), "")) != os.path.abspath(path):
                    os.unlink(path)
                    cleaned.append(os.path.relpath(path, LIB))

    with open(PLAN, "w", encoding="utf-8") as fh:
        for p in plan:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    taken = {}
    for p in plan:
        key = os.path.dirname(p["dest"])
        taken[key] = taken.get(key, 0) + 1

    print(f"   {'DRY RUN' if dry else 'IMPORTED'}")
    print(f"      filed       {len(plan)} files   "
          f"{sum(p['bytes'] for p in plan) / 2**30:.2f} GB")
    if not dry:
        print(f"      copied      {written} files   {bytes_in / 2**30:.2f} GB")
        print(f"      already     {already} filed by an earlier pass, verified "
              "by md5")
        print(f"      duplicates  {len(cleaned)} copies of this batch removed")
        for c in cleaned[:8]:
            print(f"                {c[:74]}")
        print(f"      failed      {failed}")
    print(f"      held back   {dupe_batch} repeated inside this batch")
    if nofile:
        print(f"      missing     {len(nofile)} not on disk any more")
    print("\n      albums being created:")
    for d, n in sorted(taken.items(), key=lambda kv: -kv[1])[:18]:
        print(f"        {n:3d}  {os.path.relpath(d, LIB)[:72]}")


if __name__ == "__main__":
    main()
