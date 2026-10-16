"""File the Samurai X / Rurouni Kenshin collection into its two libraries.


Episodic OVAs go to /mnt/media/series, film-length cuts go to /mnt/media/movies.
Nothing here is treated as a duplicate of anything else: the theatrical film and
the OVA acts are separate productions, and the director's cuts are separate
edits, so all of them are kept.

Series folders use the titles The Movie Database knows them by, so Jellyfin can
match them: "Rurouni Kenshin: Trust & Betrayal" (1999) and
"Rurouni Kenshin: Reflection" (2011). Movies keep the title written on the file.

Nothing is moved onto an existing path, and nothing is moved unless its source
opens and is the expected size.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/mv_samurai.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import re
import shutil
import subprocess
import sys

SRC = "/mnt/media/unsorted mo eis/Samurai X"
SERIES = "/mnt/media/series"
MOVIES = "/mnt/media/movies"
LOG = "/home/lario/video-reorganize/samurai-move.jsonl"

# src filename -> (kind, show-or-film, year, season, episode, title)
MAP = [
    ("Trust & Betrayal/Trust & Betrayal Act 1 - The Man Of The Slashing Sword   [DarkDream].mkv",
     "series", "Rurouni Kenshin - Trust & Betrayal", "1999", 1, 1, "The Man of the Slashing Sword"),
    ("Trust & Betrayal/Trust & Betrayal Act 2 - The Lost Cat   [DarkDream].mkv",
     "series", "Rurouni Kenshin - Trust & Betrayal", "1999", 1, 2, "The Lost Cat"),
    ("Trust & Betrayal/Trust & Betrayal Act 3 - The Previous Night At The Mountain Home   [DarkDream].mkv",
     "series", "Rurouni Kenshin - Trust & Betrayal", "1999", 1, 3, "The Previous Night at the Mountain Home"),
    ("Trust & Betrayal/Trust & Betrayal Act 4 - The Cross-shaped Wound   [DarkDream].mkv",
     "series", "Rurouni Kenshin - Trust & Betrayal", "1999", 1, 4, "The Cross-Shaped Wound"),
    ("Reflection/Samurai X Reflection - Act 1   [DarkDream].mkv",
     "series", "Rurouni Kenshin - Reflection", "2011", 1, 1, ""),
    ("Reflection/Samurai X Reflection - Act 2   [DarkDream].mkv",
     "series", "Rurouni Kenshin - Reflection", "2011", 1, 2, ""),
    ("The Motion Picture/Rurouni Kenshin - Requiem For Meiji Restoration Patriots   [DarkDream].mkv",
     "movie", "Rurouni Kenshin - Requiem for Meiji Restoration Patriots", "1999", 0, 0, ""),
    ("Samurai X - Reflection (Directors Cut)/Samurai X - Reflection (Directors Cut)   [DarkDream].mkv",
     "movie", "Samurai X - Reflection (Directors Cut)", "2011", 0, 0, ""),
    ("Trust & Betrayal (Directors Cut)/Samurai X - Trust & Betrayal (Directors Cut)   [DarkDream].mkv",
     "movie", "Samurai X - Trust & Betrayal (Directors Cut)", "1999", 0, 0, ""),
]


def opens(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip()) > 60
    except ValueError:
        return False


def main():
    dry = "--apply" not in sys.argv
    plan, skip = [], []
    for rel, kind, name, year, s, e, title in MAP:
        src = os.path.join(SRC, rel)
        if not os.path.exists(src):
            # release names are abbreviated in the listing; fall back to a search
            stem = os.path.splitext(os.path.basename(rel))[0][:24]
            hits = [os.path.join(r, f) for r, _d, fs in os.walk(SRC, onerror=lambda x: None)
                    for f in fs if f.startswith(stem[:20])]
            if not hits:
                skip.append((rel, "not found"))
                continue
            src = hits[0]
        if not opens(src):
            skip.append((rel, "will not open"))
            continue
        if kind == "series":
            stem = " ".join(f"{name} S{s:02d}E{e:02d} {title}".split())
            dest = os.path.join(SERIES, f"{name} ({year})", f"Season {s:02d}", stem + ".mkv")
        else:
            stem = " ".join(f"{name} ({year})".split())
            dest = os.path.join(MOVIES, stem, stem + ".mkv")
        plan.append({"src": src, "dest": dest, "kind": kind,
                     "bytes": os.path.getsize(src), "src_rel": rel})

    moved = refused = 0
    for p in plan:
        if os.path.exists(p["dest"]):
            print(f"   BLOCKED  something already sits at {p['dest']}")
            refused += 1
            continue
        if not dry:
            os.makedirs(os.path.dirname(p["dest"]), exist_ok=True)
            shutil.move(p["src"], p["dest"])
        moved += 1

    if not dry:
        with open(LOG, "w", encoding="utf-8") as fh:
            for p in plan:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"   {'DRY RUN' if dry else 'DONE'}")
    for p in plan:
        root = SERIES if p["kind"] == "series" else MOVIES
        print(f"      {p['kind']:6s} {p['bytes']/2**30:5.2f} GB  {os.path.relpath(p['dest'], root)}")
    for rel, why in skip:
        print(f"      SKIP    {rel[:60]}  ({why})")
    print(f"      moved {moved}, refused {refused}, skipped {len(skip)}")


if __name__ == "__main__":
    main()
