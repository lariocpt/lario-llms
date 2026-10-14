"""One verdict per staged file, from three independent lines of evidence.


  byte md5      -- the same file, proven
  global score  -- full-track envelope/onset correlation (mini_sweep.py)
  shape fwd/rev -- calibrated containment, both directions (mini_shape.py)
  tags          -- title + album + duration agreement

Why not one metric. The global score correlates only the shared prefix, so a
truncated copy reads ~1.0 and it cannot see that; and it called 9 files new
(The Lemon Song, The Rover, Vapor Trail...) that the library plainly has,
because a different mastering pulled the slow-envelope correlation to 0.4.
The shape metric sees span, but on 180-400 s files its classes touch at the
extremes: worst true duplicate 0.359, best non-match 0.431. So neither decides
alone: a duplicate is called when containment holds both ways, or when the
metadata is an exact match for the same release track, and where the two
metrics point different ways the file becomes CONFLICT for a human. Unique
audio is never dropped to keep a number tidy; nothing is imported into a
duplicate because a metric was unsure.

The ladder, in order, and why:

  byte-identical          proven, nothing else matters
  NO-DECODE               parked: never enters the listening tree
  low evidence            window test too coarse (short file, few windows):
                          metadata decides, otherwise UNJUDGED
  containment both ways   DUP - the library already holds this recording
  forward only            SUBSET - source is a piece of a library track: drop
  reverse only, <=1.6x    SUPERSET - the LIBRARY copy is the truncated one:
                          import, and flag that row
  reverse only, longer    NEW - an extended or live version that contains the
                          library's song is a different recording, not a fuller
                          copy of it
  global >= 0.92          the two metrics disagree -> metadata, else CONFLICT
  otherwise               NEW, unless metadata says same. Kept for review if
                          the shape score still hints at containment.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_verdict.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mini_arbiter import LIB, STAGE, norm

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DB
CONF_GLOBAL = 0.92           # global metric's calibrated same-recording floor
NOTDUP_GLOBAL = 0.50         # below this it says different; above, it is unsure
SAME_SHAPE = 0.80            # window test: worst true duplicate measured 0.839
NEW_SHAPE = 0.55             # probe: best non-match 0.581
REVIEW_SHAPE = 0.70          # above this a non-containment still smells of it
EXTEND_MAX = 1.6             # longer than this vs the library copy: different


def load():
    shape = {}
    for line in open(f"{HERE}/mini-shape.jsonl", encoding="utf-8"):
        r = json.loads(line)
        shape[r["rel"]] = r
    glob = {}
    for line in open(f"{HERE}/mini-final.jsonl", encoding="utf-8"):
        r = json.loads(line)
        glob[r["rel"]] = r
    proof = {}
    p = f"{HERE}/mini-proof.jsonl"
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            proof[r["rel"]] = r
    meta = {}
    for line in open(f"{HERE}/mini-meta.jsonl", encoding="utf-8"):
        r = json.loads(line)
        meta[r["rel"]] = r
    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    librow = {p: {"title": t or "", "album": a or "", "artist": ar or "",
                  "year": int(y or 0), "dur": float(d or 0), "br": b, "suffix": s}
              for p, t, a, ar, y, d, b, s in con.execute(
                  "select path,title,album,artist,year,duration,bit_rate,suffix"
                  " from media_file where missing=0")}
    return shape, glob, proof, meta, librow


def title_match(a, b):
    x, y = norm(a or ""), norm(b or "")
    if not x or not y:
        return False
    return x == y or (len(x) > 6 and len(y) > 6 and (x in y or y in x))


def num(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def human(n):
    """Bytes with the right unit. Divide BEFORE choosing the unit, or every
    volume in the report comes out as 0.00 GB."""
    for unit, div in (("GB", 2 ** 30), ("MB", 2 ** 20), ("kB", 2 ** 10)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def main():
    shape, glob, proof, meta, librow = load()
    out = []
    for rel, sh in sorted(shape.items()):
        g = glob.get(rel, {})
        lb = librow.get(sh.get("lib") or "", {})
        fwd, rev, gs = sh.get("fwd") or 0.0, sh.get("rev") or 0.0, g.get("score")
        lr = sh.get("lr") or 1.0
        dec_s = sh.get("dec_s")          # seconds that actually decode
        lib_dec_s = sh.get("lib_dec_s")
        try:
            nbytes = os.stat(os.path.join(STAGE, rel)).st_size
        except OSError:
            nbytes = 0
        v = {"rel": rel, "bytes": nbytes, "dur": sh["dur"], "title": sh["title"],
             "album": sh["album"], "artist": sh["artist"], "damaged": sh["damaged"],
             "src_br": sh.get("src_br"), "lib": sh.get("lib", ""), "fwd": fwd,
             "rev": rev, "lr": lr, "global": gs, "was": g.get("verdict"),
             "tried": sh.get("tried"), "nwin": sh.get("nwin"),
             "win_s": sh.get("win_s"), "low_ev": sh.get("low_evidence", False),
             "holes": sh.get("holes"), "call": sh.get("call"),
             "lib_title": lb.get("title", ""), "lib_album": lb.get("album", ""),
             "lib_br": lb.get("br"), "lib_suffix": lb.get("suffix"),
             "lib_dur": lb.get("dur", 0.0), "dec_s": dec_s, "lib_dec_s": lib_dec_s,
             "hdr_bad": sh.get("hdr_bad", False)}
        byte = bool(proof.get(rel, {}).get("byte_dupe"))
        # a title that came from a filename carries a track number
        # ("03 - Cherry Twist"), which a real title tag does not: strip it
        stem = re.sub(r"^\s*\d{1,3}\s*[-._ ]\s*", "",
                      os.path.splitext(os.path.basename(rel))[0])
        na, nb = norm(sh["album"] or ""), norm(lb.get("album", "") or "")
        album_ok = bool(nb and (na == nb or na in nb or nb in na))
        # compare DECODED seconds on both sides. A third of these files carry a
        # header duration that is plain wrong (41 minutes claimed, 6 real), and
        # a length agreement computed from two numbers, one of which is a lie,
        # proves nothing
        src_s = dec_s or v["dur"]
        lib_s = lib_dec_s or lb.get("dur", 0.0)
        meta_same = bool(lb) and album_ok \
            and abs(src_s - lib_s) <= 3.0 \
            and (title_match(sh["title"] or stem, lb.get("title", ""))
                 or title_match(stem, lb.get("title", "")))

        if byte:
            v["verdict"], v["why"] = "DUP", "byte-identical to a library file"
        elif sh.get("call") == "NO-DECODE":
            v["verdict"] = "PARK"
            v["why"] = "no decodable audio at all; damaged or unreadable container"
        elif sh.get("low_evidence"):
            if meta_same:
                v["verdict"] = "DUP"
                v["why"] = (f"window test too coarse to decide ({v['win_s']:.0f}s windows,"
                            f" {v['nwin'] or 0} of them) but the library holds the same"
                            " title on the same album at the same length")
            else:
                v["verdict"] = "UNJUDGED"
                v["why"] = (f"too short to compare ({v['win_s']:.0f}s windows,"
                            f" {v['nwin'] or 0} of them) and no metadata match - review")
        elif min(fwd, rev) >= SAME_SHAPE:
            v["verdict"] = "DUP"
            v["why"] = (f"same recording: every window of each file is found in the"
                        f" other (fwd {fwd:.3f} rev {rev:.3f})")
        elif max(fwd, rev) >= SAME_SHAPE:
            # one direction only. The lengths decide whether that means anything:
            # at equal length the asymmetry is the metric's own noise (checked
            # against the index - 16 of 17 such rows were Led Zeppelin and Busta
            # tracks the library holds at the same second count), while a real
            # length gap means one file is genuinely a piece of the other
            if 0.95 <= lr <= 1.05:
                # these files are short, so only three windows are available
                # and one-sided evidence at three windows is weak: two of the 19
                # such rows paired Come Back Clean with Fractales Pt.2 and
                # Communication Breakdown with Enthusiasm is Contagious. Equal
                # length plus a coarse shape score is not enough to delete a
                # file, so a second independent line of evidence is required
                same_title = title_match(sh["title"] or stem, lb.get("title", "")) \
                    or title_match(stem, lb.get("title", ""))
                if same_title or (gs is not None and gs >= CONF_GLOBAL):
                    v["verdict"] = "DUP"
                    backer = "the title matches" if same_title else "the global score agrees"
                    v["why"] = (f"same recording: all of the"
                                f" {'source' if fwd >= rev else 'library'} file's audio is"
                                f" found in the other (best {max(fwd, rev):.3f}), both run"
                                f" the same length ({src_s:.0f}s / {lib_s:.0f}s) and"
                                f" {backer}")
                else:
                    v["verdict"] = "CONFLICT"
                    v["why"] = (f"only {v['nwin'] or 0} shape windows available and only one"
                                f" direction agrees (best {max(fwd, rev):.3f}), global"
                                f" {gs if gs is None else round(gs, 3)} disagrees and the"
                                f" titles differ ('{sh['title']}' against"
                                f" '{lb.get('title', '')}') - review")
            elif fwd > rev:
                v["verdict"] = "SUBSET"
                v["why"] = (f"source is only a piece of a library track: all of its audio"
                            f" is inside it (fwd {fwd:.3f}) and the source is shorter"
                            f" ({src_s:.0f}s against {lib_s:.0f}s)")
            elif lr <= EXTEND_MAX:
                v["verdict"] = "SUPERSET"
                v["why"] = (f"the library copy is the truncated one: all of it is"
                            f" inside the source (rev {rev:.3f}, source"
                            f" {src_s:.0f}s against the library's {lib_s:.0f}s)"
                            " but not vice versa")
            else:
                v["verdict"] = "EXTENDED"
                v["why"] = (f"extended or live version: it contains the library track"
                            f" (rev {rev:.3f}) but runs {lr:.2f}x as long, so it is a"
                            " different recording, not a fuller copy of it")
        elif gs is None:
            v["verdict"] = "UNJUDGED"
            v["why"] = "no global score recorded - review"
        elif gs >= CONF_GLOBAL:
            # the global metric's own calibrated same-recording floor (never
            # below 0.923 on labelled pairs), not its 0.80 decision cut. When
            # the window test is merely elevated rather than proving
            # containment, the two agree rather than contradict: the shape
            # metric's own worst measured true duplicate in the 180-400 s class
            # was 0.359, so a 0.78 is not evidence of a different recording
            if max(fwd, rev) >= REVIEW_SHAPE:
                v["verdict"] = "DUP"
                v["why"] = (f"same recording: global {gs:.3f} is above the calibrated"
                            f" floor and the window test is consistent with it (best"
                            f" {max(fwd, rev):.3f}, containment not proven)")
            elif meta_same:
                v["verdict"] = "DUP"
                v["why"] = (f"global score {gs:.3f} says same recording and the library"
                            " holds the same title on the same album at the same length")
            else:
                v["verdict"] = "CONFLICT"
                v["why"] = (f"global {gs:.3f} says same recording but the window test says"
                            f" flatly not (fwd {fwd:.3f} rev {rev:.3f}) and the metadata"
                            " does not settle it - review")
        elif meta_same:
            v["verdict"] = "DUP"
            v["why"] = (f"audio metrics do not decide (global {gs:.3f}, shape"
                        f" {min(fwd, rev):.3f}) but the library holds the same title on"
                        " the same album at the same length")
        elif NOTDUP_GLOBAL <= gs < CONF_GLOBAL and max(fwd, rev) > REVIEW_SHAPE:
            # both metrics lean the same way and neither proves it: not the
            # kind of thing to decide with a threshold
            v["verdict"] = "CONFLICT"
            v["why"] = (f"global {gs:.3f} is in its ambiguous band and the window test"
                        f" hints at containment without proving it (best"
                        f" {max(fwd, rev):.3f}) - review")
        else:
            v["verdict"] = "NEW"
            v["why"] = (f"different recording: global {gs:.3f} and best window match"
                        f" {max(fwd, rev):.3f} across {sh.get('tried', 0)}"
                        " duration-matched library files")

        # Album-scoped version check, applied to anything that would otherwise
        # be imported. Same title on the same album is the same TRACK, whatever
        # the length says: a longer cut of it is an upgrade to report, not a
        # second copy to file, and filing it would sit a new file beside the
        # library's own under the same Artist/Album/NN - Title path.
        if (v["verdict"] in ("NEW", "EXTENDED", "SUPERSET") and lb and album_ok
                and (title_match(sh["title"] or stem, lb.get("title", ""))
                     or title_match(stem, lb.get("title", "")))):
            v["verdict"] = "DUP"
            v["why"] = (f"the library holds this track on the same album at"
                        f" {lib_s:.0f}s against this file's {src_s:.0f}s:"
                        " a different cut of one track, so it is reported as an"
                        " upgrade candidate rather than filed alongside it")

        # what actually enters the library: nothing that could not be decoded,
        # nothing damaged, nothing the audio or the tags tie to a file we have
        v["import_"] = (v["verdict"] in ("NEW", "EXTENDED")
                        and not sh["damaged"] and not sh.get("holes"))
        v["review"] = v["verdict"] in ("CONFLICT", "UNJUDGED", "PARK") or (
            v["verdict"] == "NEW" and max(fwd, rev) > 0.65)
        if v["verdict"] in ("DUP", "SUBSET", "SUPERSET") and lb:
            sb, lb_br = num(sh.get("src_br")), num(lb["br"])
            v["quality"] = ("source-better" if sb > lb_br
                            else "library-better" if sb < lb_br else "equal")
        out.append(v)

    with open(f"{HERE}/mini-verdict-final.jsonl", "w", encoding="utf-8") as fh:
        for v in out:
            fh.write(json.dumps(v, ensure_ascii=False) + "\n")

    def vol(rows):
        n = sum(r["bytes"] for r in rows)
        return f"{len(rows):4d} files  {human(n):>10s}"

    print("   staged audio, one verdict each:")
    tot = 0
    for k in ("DUP", "SUBSET", "SUPERSET", "EXTENDED", "NEW", "CONFLICT", "UNJUDGED",
              "PARK"):
        rows = [r for r in out if r["verdict"] == k]
        tot += sum(r["bytes"] for r in rows)
        if rows:
            print(f"      {k:9s} {vol(rows)}")
    assert abs(tot - sum(r["bytes"] for r in out)) < 1024, "a bucket went missing"
    print(f"      {'total':9s} {vol(out)}")

    dup = [r for r in out if r["verdict"] == "DUP"]
    print(f"\n   duplicates: {len(dup)}  (byte-proven"
          f" {sum(1 for r in dup if r['why'].startswith('byte'))},"
          f" containment {sum(1 for r in dup if r['why'].startswith('same recording'))},"
          f" metadata-backed {sum(1 for r in dup if 'metadata' in r['why'] or 'the same title' in r['why'])})")
    up = [r for r in dup if r.get("quality") == "source-better"]
    print(f"   duplicates where the source is the better encode: {len(up)}"
          "  -> reported as upgrade candidates, NOT imported")
    per = Counter(os.path.dirname(r["rel"]).split("/", 1)[-1] for r in up)
    for a, n in per.most_common(6):
        print(f"      {n:4d}  {a[:70]}")
    print("   lowest-confidence duplicate calls (review these first):")
    for r in sorted((r for r in dup if not r["why"].startswith("byte")),
                    key=lambda r: r["fwd"] + r["rev"])[:6]:
        print(f"      fwd {r['fwd']:.3f} rev {r['rev']:.3f} global"
              f" {(r['global'] or 0):.3f}  {r['title'][:24]:26s}"
              f" {os.path.basename(r['lib'])[:34]}")

    for k, note in (("SUPERSET", "the library's copy is the truncated one - upgrade, NOT"
                                 " imported (policy: never import a duplicate because it"
                                 " is the better encode)"),
                    ("SUBSET", "source is only part of a library track: no new audio"),
                    ("EXTENDED", "contains a library track but is a longer, different"
                                 " recording")):
        rows = [r for r in out if r["verdict"] == k]
        print(f"\n   {k} - {note} ({len(rows)})")
        for r in rows[:10]:
            print(f"      fwd {r['fwd']:.3f} rev {r['rev']:.3f} lr {r['lr']:5.2f} src"
                  f" {r['dur']:6.0f}s lib {r['lib_dur']:6.0f}s  {r['title'][:22]:24s}"
                  f" {os.path.basename(r['lib'])[:30]}")

    ver = [r for r in out if r["why"].startswith("the library holds this track")]
    print(f"\n   same track on the same album at a different length: {len(ver)}"
          "  -> reported, not filed beside the library's own copy")
    for r in ver[:8]:
        print(f"      src {r['dur']:6.0f}s lib {r['lib_dur']:6.0f}s"
              f"  {r['title'][:24]:26s} {os.path.basename(r['lib'])[:38]}")

    print("\n   to review by hand:")
    for k in ("CONFLICT", "UNJUDGED", "PARK"):
        rows = [r for r in out if r["verdict"] == k]
        for r in rows[:14]:
            print(f"      {k:8s} fwd {r['fwd']:.3f} rev {r['rev']:.3f} glob"
                  f" {(r['global'] or 0):.3f} dmg {int(bool(r['damaged']))} nwin"
                  f" {r['nwin'] or 0:2d} lr {r['lr']:5.2f}  {r['title'][:20]:22s}"
                  f" {os.path.basename(r['lib'])[:28]}")
        if len(rows) > 14:
            print(f"      ... {len(rows) - 14} more {k}")
    near = [r for r in out if r["review"] and r["verdict"] == "NEW"]
    print(f"      {len(near)} NEW files still flagged for review (shape score > 0.65"
          " but not containment)")
    for r in sorted(near, key=lambda r: -max(r["fwd"], r["rev"]))[:8]:
        print(f"      NEW?     fwd {r['fwd']:.3f} rev {r['rev']:.3f} glob"
              f" {(r['global'] or 0):.3f}  {r['title'][:20]:22s}"
              f" {os.path.basename(r['lib'])[:28]}")

    imp = [r for r in out if r["import_"]]
    print("\n   audio to import, by source folder:")
    grp = defaultdict(lambda: [0, 0])
    for r in imp:
        k = "/".join(r["rel"].split("/")[:2])[:64]
        grp[k][0] += 1
        grp[k][1] += r["bytes"]
    for k, (n, b) in sorted(grp.items(), key=lambda kv: -kv[1][0])[:18]:
        print(f"      {n:4d}  {human(b):>10s}  {k}")
    hold = [r for r in out if r["verdict"] == "NEW" and not r["import_"]]
    print(f"\n   imports: {len(imp)} files, {human(sum(r['bytes'] for r in imp))}")
    print(f"   held back from that: {len(hold)} files,"
          f" {human(sum(r['bytes'] for r in hold))} damaged - parked, never indexed")
    print(f"   parked undecodable: {len([r for r in out if r['verdict'] == 'PARK'])}"
          f"  on hold for review: {len([r for r in out if r['verdict'] in ('CONFLICT', 'UNJUDGED')])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
