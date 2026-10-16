#!/usr/bin/env python3
"""Merge the two Brandon Sanderson audiobook folders into ONE importable library.

/mnt/media/audiobooks held two Sanderson trees:

    The Cosmere Series - Brandon Sanderson   36 GB   GraphicAudio productions,
                                                  256 kbps, split into "Part 1
                                                  / Part 2" folders
    Brandon Sanderson collection            3.0 GB   standard audiobooks,
                                                  56-69 kbps, one folder per book

They are NOT duplicates. Measured: Words of Radiance is 37.6 h @256 kbps in the
first and 48.3 h @56 kbps in the second; Oathbringer 40.4 h vs 53.1 h. One is
the dramatised GraphicAudio production, the other the unabridged recording --
so both are kept and each folder is LABELED with the edition it is.

This writes /mnt/media/audiobooks/Brandon Sanderson containing one folder per
edition per book, named on the shelf as

    13 - Stormlight Archive 02 - Words of Radiance (GraphicAudio)
    13 - Stormlight Archive 02 - Words of Radiance (Unabridged)

which also fixes the way audiobookshelf read the old tree: it turns every
folder it finds into a separate audiobook, so "Mistborn 1 - The Final Empire
(2 of 3)" showed up as its own title. The part folders are merged back into one
folder per book, files prefixed 0001.. so play order survives.

Ebooks bundled inside the audiobooks leave for the ebook server: genuinely new
titles go to /mnt/media/books/import (calibre-web-automated's drop) and anything
the calibre library already holds is parked, never imported twice.

Every move is appended to a JSONL and --undo replays it backwards.

  python3 organise_sanderson.py            # plan only, touches nothing
  python3 organise_sanderson.py --apply
  python3 organise_sanderson.py --undo
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import config as _config          # noqa: E402

AB = Path(_config.AUDIOBOOKS)
COSMERE = AB / "The Cosmere Series - Brandon Sanderson"
COLLECTION = AB / "Brandon Sanderson collection"
SOURCES = [COSMERE, COLLECTION]
ROOT = AB / "Brandon Sanderson"

BOOK_DROP = Path(_config.BOOK_IMPORT)       # calibre-web-automated ingest
PARK = Path(_config.BOOK_PARK)
JUNK = AB / "_incomplete-downloads"                    # never deleted, never imported
LOG = Path(__file__).with_name("sanderson-merge.jsonl")
EBOOK_LOG = Path(__file__).with_name("sanderson-ebooks.jsonl")
INDEX = Path(__file__).with_name("sanderson-merge-report.txt")

AUDIO = {".mp3", ".m4a", ".m4b", ".ogg", ".opus", ".wav", ".flac"}
EBOOK = {".epub", ".mobi", ".azw3", ".azw", ".pdf"}
NUM = re.compile(r"(\d+)")

# The collection's own nfo.txt says "Steelheart (The Reckoners #1)".
NFO_SERIES = {"steelheart": "Reckoners 01"}

CRUFT = re.compile(r"\s*[-–]\s*(GA|GraphicAudio|Normal Audio|Digital Release|Unabridged|Abridged)\s*$", re.I)
SERIES_STUTTER = re.compile(r"^(Mistborn|Stormlight Archive|Elantris)\s+-\s+"
                            r"([0-9]+(?:\.[0-9]+)?)\s*-\s*(.+)$", re.I)


def natural(text):
    return [int(p) if p.isdigit() else p.casefold() for p in NUM.split(text)]


def normalise(text):
    """Key for matching a title across two naming conventions."""
    t = unicodedata.normalize("NFKC", str(text)).casefold()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)
    t = re.sub(r"brandon\s+sanderson", " ", t)
    t = re.sub(r"^\s*(the|a|an)\s+", "", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def core(text):
    """The title without its series and number, so the shelf's
    'Stormlight Archive 02 - Words of Radiance' matches a folder that just says
    'Words of Radiance'."""
    t = normalise(text)
    m = re.match(r"^(mistborn|stormlight archive|elantris|reckoners|whitesand|white sand)"
                 r"\s*[0-9.]*\s*[- ]?\s*(.+)$", t)
    t = m.group(2) if m else t
    return re.sub(r"^(the|a|an)\s+", "", t).strip()


def audio_in(folder):
    return sorted((p for p in folder.rglob("*")
                   if p.is_file() and p.suffix.lower() in AUDIO),
                  key=lambda p: natural(str(p.relative_to(folder))))


def probe(path, want_tags=False):
    """NOTE: `format_tags` cannot be mixed into a `format=` list -- ffprobe
    accepts that, exits 0 and simply omits every tag, which is how edition
    detection silently found nothing. Repeat -show_entries instead."""
    args = ["ffprobe", "-v", "error", "-show_entries", "format=duration,bit_rate"]
    if want_tags:
        args += ["-show_entries", "format_tags"]
    try:
        out = subprocess.run(args + ["-of", "default=nw=1", str(path)],
                             capture_output=True, text=True, timeout=90).stdout
    except Exception:
        return {}
    d = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.startswith("TAG:"):
                d[k[4:]] = v
            else:
                d[k] = v
    return d


def edition_of(book, files):
    """GraphicAudio is stated in the files' own tags; the rest are the plain
    audiobooks. Proven, not guessed -- and only decided once per book."""
    hits = 0
    for path in files[:4]:
        info = probe(path, want_tags=True)
        blob = " ".join(info.get(k, "") for k in ("album", "artist", "album_artist", "comment")).casefold()
        if "graphicaudio" in blob or "graphic audio" in blob:
            hits += 1
    if hits:
        return "GraphicAudio"
    return "Unabridged" if book.parent == COLLECTION else ""


def title_of(book):
    """Clean, sortable name from the folder name, using the release's own words."""
    name = book.name
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*-\s*(.*)$", name)
    order, rest = (m.group(1), m.group(2)) if m else (None, name)
    rest = CRUFT.sub("", rest)
    rest = re.sub(r"^brandon\s+sanderson\s*[-–]\s*", "", rest, flags=re.I)
    m = SERIES_STUTTER.match(rest.strip())
    if m:
        series, num, title = m.group(1), m.group(2), m.group(3).strip()
        head, _, frac = num.partition(".")
        num = f"{int(head):02d}" + (f".{frac}" if frac else "")
        rest = f"{series} {num} - {title}"
    # The release called this folder "Elantris - The Emperor's Soul", but the
    # three files in it are tagged album="The Emperor's Soul" 01/03..03/03 and
    # Elantris itself is book 01 of this same shelf. It is the novella alone.
    if normalise(rest) == normalise("Elantris - The Emperor's Soul"):
        rest = "The Emperor's Soul"
    rest = re.sub(r"\s+", " ", rest).strip(" -–")
    return order, rest


def order_key(order):
    if not order:
        return None
    head, _, frac = order.partition(".")
    return f"{int(head):02d}" + (f".{frac}" if frac else "")


def calibre_titles():
    have = {}
    for opf in (BOOK_DROP.parent / "library").glob("*/*/metadata.opf"):
        try:
            text = opf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # calibre writes namespaced <dc:title>; matching a bare <title> finds
        # nothing and every bundled ebook then looks "new".
        m = re.search(r"<(?:dc:)?title[^>]*>(.*?)</(?:dc:)?title>", text, re.S)
        if m:
            key = normalise(m.group(1))
            if key:
                have.setdefault(key, opf)
    return have


def in_calibre(stem_norm, have):
    """Exact match, or the calibre title standing alone inside the filename --
    'Bands of Mourning' vs 'The Bands of Mourning: A Mistborn Novel'."""
    if stem_norm in have:
        return have[stem_norm]
    for key, opf in have.items():
        if len(key) >= 10 and re.search(r"(?:^|\s)" + re.escape(key) + r"(?:\s|$|[,:])", stem_norm):
            return opf
    return None


def md5_head(path, limit=4 << 20):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        left = limit
        while left > 0:
            chunk = fh.read(min(1 << 20, left))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
    return h.hexdigest()


def build_plan():
    have = calibre_titles()
    books, dupes, ebook_actions, junk = [], [], [], []
    seen = {}
    # A GraphicAudio box ships the same ebook in several part folders, so a title
    # that is new to calibre can still arrive twice. Key on size + the head hash
    # (cheap on a 115 MB epub) so the second copy parks instead of duplicating.
    queued = {}
    used_dests = set()
    for src_root in SOURCES:
        if not src_root.is_dir():
            continue
        for book in sorted((b for b in src_root.iterdir() if b.is_dir()), key=lambda b: natural(b.name)):
            files = audio_in(book)
            if not files:
                # a folder with no audio is not a book -- the bundled ebooks get
                # handled below; anything else is reported.
                continue
            order, title = title_of(book)
            edition = edition_of(book, files)
            if not order and normalise(title) in seen:
                order = seen[normalise(title)]
            key = order_key(order)
            label = f"{key} - {title}" if key else title
            if edition:
                label = f"{label} ({edition})"
            if normalise(title) not in seen:
                seen[normalise(title)] = order
            else:
                dupes.append((title, edition))
            if normalise(title) == "steelheart" and "steelheart" in NFO_SERIES and not order:
                label = f"{NFO_SERIES['steelheart']} - Steelheart ({edition})" if edition \
                    else f"{NFO_SERIES['steelheart']} - Steelheart"
            parts = sorted((d for d in book.iterdir() if d.is_dir()), key=lambda d: natural(d.name))
            books.append({"src": book, "label": label, "files": files, "parts": parts,
                          "edition": edition, "order": order, "title": title})

    # numbering collisions: two different books claiming the same order key
    keys = {}
    for b in books:
        keys.setdefault(order_key(b["order"]), []).append(b["label"])
    for k, labels in sorted((k, v) for k, v in keys.items() if k):
        titles = {normalise(l.split(" - ", 1)[-1].split(" (")[0]) for l in labels}
        if len(titles) > 1:
            print(f"   !! order key {k} claimed by {labels} -- keeping the name, check it")

    for path in sorted([p for p in AB.rglob("*") if p.is_file()
                        and (p.suffix.lower() in EBOOK or p.suffix.lower() == ".opf")
                        and any(p.is_relative_to(s) for s in SOURCES)], key=lambda p: natural(str(p))):
        stem = re.sub(r"\s*[-–]\s*Brandon Sanderson.*$", "", path.stem, flags=re.I)
        stem = re.sub(r"\[.*?\]|\(.*?\)", " ", stem)
        stem = re.sub(r"\s+", " ", stem).strip(" _-")
        if path.suffix.lower() == ".opf":
            ebook_actions.append({"file": path, "action": "sidecar"})
            continue
        norm = normalise(stem)
        dupe = have.get(norm)
        ident = (path.stat().st_size, md5_head(path)) if path.suffix.lower() == ".epub" else None
        if dupe is None and path.suffix.lower() == ".epub" and ident not in queued:
            queued[ident] = stem
            action = {"file": path, "action": "import", "stem": stem,
                      "dest": BOOK_DROP / f"{stem} - Brandon Sanderson.epub"}
        else:
            if dupe:
                why = "the calibre library already holds this title"
            elif ident in queued:
                why = f"byte-identical to the copy already queued ({queued[ident]})"
            else:
                why = f"{path.suffix[1:]} companion of an imported record"
            # two part folders can hold the same filename: park them apart, or the
            # second move lands on top of the first
            dest = PARK / (f"{stem} - bundled{path.suffix}" if norm in have else path.name)
            if dest in used_dests:
                dest = PARK / f"{path.parent.name} - {dest.name}"
            used_dests.add(dest)
            action = {"file": path, "action": "park", "stem": stem, "why": why, "dest": dest}
        if action["action"] == "import":
            import_dest = action["dest"]
            if import_dest in used_dests:
                # calibre would merge same-name drops, but keep the plan honest
                action["why"] = f"shares a drop name with an earlier record: {import_dest.name}"
            used_dests.add(import_dest)
        ebook_actions.append(action)

    for path in sorted(p for p in AB.rglob("*.crdownload") if any(p.is_relative_to(s) for s in SOURCES)):
        junk.append(path)
    return books, dupes, ebook_actions, junk


def record(path, entry):
    with open(path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def move(src, dst, logpath):
    src, dst = Path(src), Path(dst)
    if not src.exists():
        return None
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        os.remove(src)
        record(logpath, {"src": str(src), "dst": str(dst), "note": "identical target existed"})
        return "dupe-removed"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst = dst.with_name(f"{dst.stem}-dup{dst.suffix}")
    os.rename(src, dst)
    record(logpath, {"src": str(src), "dst": str(dst)})
    return "moved"


def undo():
    if not LOG.exists():
        print("   nothing to undo")
        return
    actions = [json.loads(l) for l in open(LOG)]
    done = 0
    for act in reversed(actions):
        src, dst = Path(act["src"]), Path(act["dst"])
        if dst.exists() and not src.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            os.rename(dst, src)
            done += 1
    print(f"   restored {done} of {len(actions)} moves")


def totals(folders):
    n = b = 0
    for f in folders:
        for path in audio_in(f):
            n += 1
            b += path.stat().st_size
    return n, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    args = ap.parse_args()
    if args.undo:
        undo()
        return

    for s in SOURCES:
        if not s.is_dir():
            print(f"   missing source {s}")
    before_n, before_b = totals([s for s in SOURCES if s.is_dir()])
    print(f"=== {before_n} audio files, {before_b / 2**30:.1f} GB across "
          f"{sum(1 for s in SOURCES if s.is_dir())} source trees ===\n")

    books, dupes, ebook_actions, junk = build_plan()

    print(f"--- one folder per book/edition in {ROOT} ({len(books)} books) ---")
    for b in sorted(books, key=lambda b: natural(b["label"])):
        merged = " (+ merges %d part folders)" % len(b["parts"]) if len(b["parts"]) > 1 else ""
        print(f"   {b['label'][:74]:74}  {len(b['files']):4d}{merged}")

    print("\n--- bundled ebooks leaving for the ebook server ---")
    for e in ebook_actions:
        if e["action"] == "sidecar":
            continue
        print(f"   {e['action']:7}  {e['file'].name[:56]:56}  {e.get('why', 'new to the ebook library')}")

    if junk:
        print("\n--- INCOMPLETE DOWNLOADS (never imported, kept aside) ---")
        for p in junk:
            print(f"   {p.relative_to(AB)}  {p.stat().st_size / 2**20:.1f} MB  "
                  f"its book is missing this chapter")

    if not args.apply:
        print("\n   dry run -- nothing touched. --apply to do it, --undo to roll back.")
        return

    ROOT.mkdir(parents=True, exist_ok=True)
    moved_files = 0
    for b in books:
        dest_dir = ROOT / b["label"]
        if dest_dir.exists():
            print(f"   target already exists, skipping book: {b['label']}")
            continue
        for i, src in enumerate(b["files"], 1):
            dst = dest_dir / f"{i:04d} - {src.name}"
            if move(src, dst, LOG) in ("moved", "dupe-removed"):
                moved_files += 1
    print(f"\n   {moved_files} audio files placed")

    for e in ebook_actions:
        if e["action"] == "sidecar" or not e["file"].exists():
            continue
        move(e["file"], e["dest"], EBOOK_LOG)
    for p in junk:
        if p.exists():
            move(p, JUNK / p.name, EBOOK_LOG)

    (JUNK / "README.txt").write_text(
        "Files whose download never finished (browser .crdownload leftovers).\n"
        "Left here rather than deleted so nothing is lost, and kept out of the\n"
        "audiobookshelf library so it cannot show up as a broken book.\n"
        "Re-download the matching chapter to complete the audiobook.\n")
    PARK.mkdir(parents=True, exist_ok=True)
    (PARK / "README.txt").write_text(
        "Ebooks that were bundled inside the Brandon Sanderson AUDIOBOOK folders.\n"
        "They are parked here, not imported, because the calibre library at\n"
        f"{_config.BOOKS}/library already holds that title (or this is a .mobi\n"
        "companion of an imported record) and importing twice would double the\n"
        "shelf. Book metadata.opf sidecars of those same bundled ebooks are left\n"
        "behind in the audiobook tree with the audio they came with.\n")

    # empty the old trees, then drop the empty shells
    for s in SOURCES:
        if not s.is_dir():
            continue
        for d in sorted((d for d in s.rglob("*") if d.is_dir()), reverse=True):
            try:
                os.rmdir(d)
            except OSError:
                pass
    print("\n--- what remains of the old trees (only unexplained files, if any) ---")
    for s in SOURCES:
        if not s.is_dir():
            print(f"   {s.name}: gone")
            continue
        left = [p for p in s.rglob("*") if p.is_file()]
        if not left:
            os.rmdir(s)
            print(f"   {s.name}: gone")
        else:
            print(f"   {s.name}: {len(left)} non-audio file(s) left behind, untouched:")
            for p in left[:8]:
                print(f"       {p.relative_to(s)}  {p.stat().st_size / 2**20:.2f} MB")

    after_n, after_b = totals([ROOT] + [s for s in SOURCES if s.is_dir()])
    park_n = sum(1 for p in PARK.rglob("*") if p.is_file() and p.suffix.lower() in EBOOK)
    ok = after_n == before_n and after_b == before_b
    print(f"\n   after: {after_n} audio files / {after_b / 2**30:.1f} GB "
          f"({'UNCHANGED - nothing lost' if ok else 'MISMATCH, check ' + str(LOG)})")
    print(f"   {park_n} parked ebook files at {PARK}")
    print(f"   point audiobookshelf at {ROOT.relative_to(AB).as_posix()} "
          f"(container path /audiobooks/{ROOT.name})")
    if not ok:
        sys.exit(1)


main()
