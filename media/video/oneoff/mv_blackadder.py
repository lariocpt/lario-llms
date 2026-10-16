"""File the Blackadder Complete Ultimate Edition into the series library.


Source: /mnt/media/un2/The Black Adder ... DVDRip 576p x264 AC3 (MKV)
        38 files, 12.6 GB, PAL DVD (704x574 anamorphic, 25 fps, AC3 192k,
        VobSub subs). The 8 files whose names end "+C" carry a second AC3
        track: the optional commentary. Nothing here is a duplicate -- no
        Blackadder existed on this box before this drop.

The 24 numbered episodes already arrive correctly numbered, so series 1-4 go
straight to Season 01-04 with their titles tidied.

The 14 files on discs 5 and 6 are specials and DVD extras. Their filenames
carry no numbers, and guessing one from length would mislabel them: this set
contains four separate ~30 minute items and several near-identical 5-minute
interview clips. They are numbered against TheTVDB season 0 for Blackadder,
each match confirmed by runtime as well as name:

    S00E01 The Cavalier Years              15m file / 15m listed
    S00E02 Blackadder's Christmas Carol    43m    / 45m
    S00E03 Blackadder Back & Forth         33m    / 35m
    S00E05 Blackadder Rides Again          59m    / 60m
    S00E06 Stephen Fry in Africa           15m    / 15m
    S00E07 Richard Curtis & Ben Elton      16m    / 16m
    S00E08 Tony Robinson in London         14m    / 15m
    S00E09 Baldrick's Video Diary          29m    / 30m
    S00E13 Miranda Richardson at the BBC    4m    /  5m
    S00E14 Hilary Bevan Jones at BAFTA      4m    /  5m
    S00E15 Hugh Laurie on set in Hollywood  4m    /  5m
    S00E16 Rik Mayall in London             4m    /  4m
    S00E18 Interview - Rowan Atkinson      23m    / 30m

S00E18 is the one uncertain number: the title matches verbatim but the file is
23 minutes against 30 listed, while S00E19 (Rowan Atkinson and producer John
Lloyd driving to Alnwick Castle, 24m) matches on length. Name won over length
here because TheTVDB runtimes are rounded and this title is the DVD's own.

"Costumes Revisited" (10m) is not in TheTVDB's season 0 at all, so it is given
a number from the gap in the list rather than left unnumbered in the show
folder, where it would land as "Unknown Episode". If Jellyfin labels it wrong,
the fix is to drop the number, not to argue with it.

The "+C" suffix is dropped from filenames because the commentary is not a
second copy of the episode: it travels as the file's second audio track.

NOTE on aspect ratio. Every file is anamorphic: 704x574 stored, 4:3 meant.
Every destination therefore gets a sidecar .aspect recording its stored size
and its true sample/display aspect, so a later encode can be checked against
it. A re-encode that flattens SAR to 1:1 shows the episode squashed sideways.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/mv_blackadder.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import shutil
import subprocess
import sys

SRC = "/mnt/media/un2/The Black Adder Blackadder Complete DVDRip 576p x264 AC3 (MKV)"
DST = "/mnt/media/series/Blackadder (1983)"
LOG = "/home/lario/video-reorganize/blackadder-move.jsonl"

S1 = os.path.join(SRC, "01-Series 1 (The Black Adder)")
S2 = os.path.join(SRC, "02-Series 2 (Blackadder II)")
S3 = os.path.join(SRC, "03-Series 3 (Blackadder III)")
S4 = os.path.join(SRC, "04-Series 4 (Blackadder Goes Forth)")
SP = os.path.join(SRC, "05-The Specials (Disc 5)")
EX = os.path.join(SRC, "06-Blackadder Rides Again (Disc 6)")

SHOW = "Blackadder"

# src filename -> season folder, and the title to use for it.
MAP = {
    # --- Series 1: The Black Adder ---
    f"{S1}/Blackadder S01E01 The Foretelling.mkv": "Season 01",
    f"{S1}/Blackadder S01E02 The Queen Of Spain's Beard.mkv": "Season 01",
    f"{S1}/Blackadder S01E03 The Archbishop.mkv": "Season 01",
    f"{S1}/Blackadder S01E04 Born To Be King.mkv": "Season 01",
    f"{S1}/Blackadder S01E05 Witchsmeller Persuivant.mkv": "Season 01",
    f"{S1}/Blackadder S01E06 The Black Seal.mkv": "Season 01",
    # --- Series 2: Blackadder II ---
    f"{S2}/Blackadder S02E01 Bells+C.mkv": "Season 02",
    f"{S2}/Blackadder S02E02 Head.mkv": "Season 02",
    f"{S2}/Blackadder S02E03 Potato.mkv": "Season 02",
    f"{S2}/Blackadder S02E04 Money+C.mkv": "Season 02",
    f"{S2}/Blackadder S02E05 Beer.mkv": "Season 02",
    f"{S2}/Blackadder S02E06 Chains+C.mkv": "Season 02",
    # --- Series 3: Blackadder the Third ---
    f"{S3}/Blackadder S03E01 Dish And Dishonesty.mkv": "Season 03",
    f"{S3}/Blackadder S03E02 Ink And Incapability+C.mkv": "Season 03",
    f"{S3}/Blackadder S03E03 Nob And Nobility.mkv": "Season 03",
    f"{S3}/Blackadder S03E04 Sense And Senility.mkv": "Season 03",
    f"{S3}/Blackadder S03E05 Amy And Amiability+C.mkv": "Season 03",
    f"{S3}/Blackadder S03E06 Duel And Duality+C.mkv": "Season 03",
    # --- Series 4: Blackadder Goes Forth ---
    f"{S4}/Blackadder S04E01 Captain Cook.mkv": "Season 04",
    f"{S4}/Blackadder S04E02 Corporal Punishment.mkv": "Season 04",
    f"{S4}/Blackadder S04E03 Major Star+C.mkv": "Season 04",
    f"{S4}/Blackadder S04E04 Private Plane.mkv": "Season 04",
    f"{S4}/Blackadder S04E05 General Hospital.mkv": "Season 04",
    f"{S4}/Blackadder S04E06 Goodbyeee+C.mkv": "Season 04",
    # --- Specials, numbered from TheTVDB season 0 ---
    f"{SP}/Blackadder-The Cavalier Years.mkv": "Season 00/S00E01 The Cavalier Years",
    f"{SP}/Blackadder-Blackadder's Christmas Carol.mkv": "Season 00/S00E02 Blackadder's Christmas Carol",
    f"{SP}/Blackadder-Back And Forth.mkv": "Season 00/S00E03 Blackadder Back & Forth",
    f"{SP}/Blackadder-Baldrick's Diary.mkv": "Season 00/S00E09 Baldrick's Video Diary",
    # --- Disc 6 extras, numbered from TheTVDB season 0 ---
    f"{EX}/Blackadder Rides Again.mkv": "Season 00/S00E05 Blackadder Rides Again",
    f"{EX}/Costumes Revisited.mkv": "Season 00/S00E10 Costumes Revisited",
    f"{EX}/Stephen Fry Interview.mkv": "Season 00/S00E06 Stephen Fry in Africa",
    f"{EX}/Richard Curtis And Ben Elton Interview.mkv": "Season 00/S00E07 Richard Curtis and Ben Elton in Soho",
    f"{EX}/Tony Robinson Interview.mkv": "Season 00/S00E08 Tony Robinson in London",
    f"{EX}/Miranda Richardson Interview.mkv": "Season 00/S00E13 Miranda Richardson at the BBC",
    f"{EX}/Hilary Bevan Jones Interview.mkv": "Season 00/S00E14 Hilary Bevan Jones at BAFTA",
    f"{EX}/Hugh Laurie Interview.mkv": "Season 00/S00E15 Hugh Laurie on set in Hollywood",
    f"{EX}/Rik Mayall Interview.mkv": "Season 00/S00E16 Rik Mayall in London",
    f"{EX}/Rowan Atkinson Interview.mkv": "Season 00/S00E18 Interview - Rowan Atkinson",
}

# Files that are not episodes at all and so must not be filed as one.
NOT_MEDIA = {"Info.txt"}


def target_for(src):
    """Where this file goes, with release junk stripped from the name."""
    rel = MAP[src]
    base = os.path.basename(src)[:-4]                       # drop .mkv
    if "/" in rel:                                           # specials: number+title given
        return os.path.join(DST, rel, f"{SHOW} {base}.mkv").replace(f"{SHOW} Blackadder ", f"{SHOW} ")
    season = rel
    name = base.replace("Blackadder ", "", 1)                # -> "S01E01 The Foretelling"
    name = name.replace("+C", "")                            # commentary rides as audio 2
    return os.path.join(DST, season, f"{SHOW} {name}.mkv")


def probe(path):
    j = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
        capture_output=True, text=True).stdout)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    return {
        "codec": v.get("codec_name"), "w": v.get("width"), "h": v.get("height"),
        "sar": v.get("sample_aspect_ratio") or "1:1",
        "dar": v.get("display_aspect_ratio") or "",
        "fps": v.get("avg_frame_rate"), "field": v.get("field_order"),
        "dur": float(j.get("format", {}).get("duration") or 0),
        "n_a": sum(1 for s in j["streams"] if s["codec_type"] == "audio"),
        "n_s": sum(1 for s in j["streams"] if s["codec_type"] == "subtitle"),
    }


def main():
    apply = "--apply" in sys.argv
    print(f"   {'APPLY' if apply else 'DRY RUN'}   Blackadder -> {DST}")
    missing = [s for s in MAP if not os.path.exists(s)]
    if missing:
        print(f"   {len(missing)} sources in the map do not exist:")
        for m in missing:
            print(f"      {os.path.relpath(m, SRC)}")
        return 1
    on_disk = {os.path.join(r, f) for r, _d, x in os.walk(SRC)
               for f in x if f.endswith(".mkv")}
    unmapped = on_disk - set(MAP)
    if unmapped:
        print(f"   {len(unmapped)} video files on disk are NOT in the map -- refusing to guess:")
        for u in sorted(unmapped):
            print(f"      {os.path.relpath(u, SRC)}")
        return 1

    recs, refused = [], []
    for src in sorted(MAP):
        dst = target_for(src)
        if os.path.exists(dst):
            refused.append((src, "destination already exists"))
            continue
        before = probe(src)
        recs.append({"src": src, "dst": dst, "bytes": os.path.getsize(src), "before": before})

    for season in ("Season 01", "Season 02", "Season 03", "Season 04", "Season 00"):
        n = sum(1 for r in recs if f"/{season}/" in r["dst"])
        if n:
            print(f"      {season}: {n} files")
    anam = sum(1 for r in recs if r["before"]["sar"] not in ("1:1", None))
    print(f"\n   {len(recs)} files, {sum(r['bytes'] for r in recs)/2**30:.1f} GB")
    print(f"   anamorphic (SAR is not square): {anam} of {len(recs)}")
    for r in recs[:3]:
        b = r["before"]
        print(f"      {b['w']}x{b['h']} SAR {b['sar']} DAR {b['dar']}  -> {b['w']*int(b['sar'].split(':')[0])/int(b['sar'].split(':')[1]):.0f}px wide on screen")
    for src, why in refused:
        print(f"   REFUSED {os.path.relpath(src, SRC)}: {why}")

    if not apply:
        print("\n   dry run -- nothing moved")
        return 0

    moved = 0
    for r in recs:
        os.makedirs(os.path.dirname(r["dst"]), exist_ok=True)
        shutil.move(r["src"], r["dst"])
        after = probe(r["dst"])                      # must open at its new home
        ok = abs(after["dur"] - r["before"]["dur"]) < 2.0 and after["codec"] == r["before"]["codec"]
        # the sidecar that records the true shape, for the encode to be checked against
        with open(r["dst"] + ".aspect", "w") as fh:
            fh.write(f"{r['dst']}\nstored {after['w']}x{after['h']}  SAR {after['sar']}  DAR {after['dar']}\n")
        r["verified"] = ok
        moved += 1 if ok else 0
        r["verified"] = ok
        if not ok:
            print(f"      PROBE FAILED AT DESTINATION: {r['dst']}")
    with open(LOG, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n   moved {moved}, refused {len(refused)}, logged to {os.path.basename(LOG)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
