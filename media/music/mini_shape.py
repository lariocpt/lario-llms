"""Definitive classification: calibrated shape metric, exhaustive, both ways.


Why both directions. "Same recording" is not one question:

  forward  -- every window of the SOURCE is found in the library copy
  reverse  -- every window of the library copy is found in the source

Four answers, and they mean different things:

  both high          SAME        the library already has it, whole
  forward only       SUBSET      the source is a piece of a library track
                                 (truncated copy): nothing to import
  reverse only       SUPERSET    the LIBRARY copy is the short one, the source
                                 is complete: import it and flag the library row
  both low           NEW         different recording

A one-directional comparison cannot tell SUBSET from SUPERSET, and the
full-track global score cannot tell them either: it correlates the first
min(len) frames, so a half-length copy still reads ~1.0. That is why the
durations in the index are not trusted here -- these files are decoded.

Thresholds come from mini_covprobe.py (90 s windows, 1 s smoothing): same
recording never below 0.839, different audio never above 0.581, measured on
200 pairs of known truth. Anything between 0.55 and 0.80 stays BAND for a
human, and a file with fewer than two usable windows is NOT-JUDGED.

Exhaustive by construction: every library file whose decoded length lands
within +-3 s is compared, not only the ones whose title looks similar, so a
duplicate under a wrong title is still found.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_shape.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import pickle
import re
import sqlite3
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mini_arbiter as A
from mini_arbiter import LIB, STAGE, norm
from mini_cov import compare, good_mask, SAME_AT, DIFF_AT, win_for, low_evidence

OUT = f"{WORK}/mini-shape.jsonl"
from paths import DB
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
os.makedirs(WORK, exist_ok=True)   # one evidence root for the whole pass
DTOL = 3.0
FPS = 1.0 / A.HOP    # envelope frames per second (HOP = 0.02 s -> 50)

# words that identify a recording with nothing: they appear on nearly every
# release of everything, so a shared one buys no candidate
STOP = {"the", "and", "for", "with", "from", "this", "that", "than", "then",
        "feat", "ftte", "feat", "vers", "remix", "remaster", "version", "mix",
        "live", "studio", "album", "single", "explicit", "clean", "radio",
        "edit", "original", "extended", "instrumental", "acoustic", "track",
        "part", "disc", "cd1", "cd2", "mp3", "flac", "m4a", "wav", "ogg"}


def words(text):
    """Meaningful lowercase word tokens of a title or filename stem."""
    out = set()
    for w in re.split(r"[^a-z0-9]+", norm(text or "")):
        if len(w) >= 4 and w not in STOP and not w.isdigit():
            out.add(w)
    return out
EXTEND_MAX = 1.6     # a source this much longer than the library copy is an
                     # extended/live version, not a fuller copy of one track
_lock = threading.Lock()
_holes = {}          # path -> good mask, so each damaged file is decoded once


def holes(path):
    with _lock:
        if path not in _holes:
            _holes[path] = good_mask(path)
        return _holes[path]


def both(fa, fb, ga, gb, win_s=None):
    """(forward, reverse) shape scores."""
    return (compare(fa, fb, ga, gb, win_s), compare(fb, fa, gb, ga, win_s))


def call(fwd, rev, lr):
    """Verdict from the two containment scores."""
    f, r = fwd["mean_best"], rev["mean_best"]
    if min(f, r) >= SAME_AT:
        return "SAME"
    if f >= SAME_AT > r:
        return "SUBSET"
    if r >= SAME_AT > f:
        # all of the library file is found inside the source. When the source
        # is much longer, that is an extended or live version -- a different
        # recording that happens to contain the same song -- not a fuller copy
        # of it, so it is not a SUPERSET and the library row is not blamed
        return "SUPERSET" if lr <= EXTEND_MAX else "EXTENDED"
    if max(f, r) <= DIFF_AT:
        return "NEW"
    return "BAND"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    if os.path.exists(A.CACHE):
        with open(A.CACHE, "rb") as fh:
            A._cache.update(pickle.load(fh))
        print(f"   envelopes: {len(A._cache)}", file=sys.stderr)

    con = sqlite3.connect(DB, uri=True)
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    libd, by_title, by_word = {}, defaultdict(list), defaultdict(set)
    for p, d, t in con.execute("select path,duration,title from media_file"
                              " where missing=0"):
        libd[p] = float(d or 0)
        if t:
            by_title[norm(t)].append(p)
        # a word index over titles AND filenames. Half these files carry a
        # title tag that is literally the filename ("5 Dazed And Confused.mp3",
        # the scene-pack habit), so by_title matches nothing, and a 27-minute
        # live take matches nothing on duration either. Words are the handle
        # left, and the one no broken header can defeat.
        for w in words(t) | words(os.path.splitext(os.path.basename(p))[0]):
            by_word[w].add(p)
    buckets = defaultdict(list)
    for p, d in libd.items():
        buckets[int(round(d))].append(p)

    cands = json.load(open(f"{WORK}/mini-cands.json", encoding="utf-8"))
    rows = [json.loads(l) for l in open(f"{WORK}/mini-final.jsonl", encoding="utf-8")
            if l.strip()]
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["rel"])
            except ValueError:
                pass

    def work(rec):
        rel = rec["rel"]
        sp = os.path.join(STAGE, rel)
        d = float(rec["dur"] or 0)
        # a file's own duration is only a hint (broken headers read 0), so ask
        # for at least enough decode to carry a window; long files are decoded
        # whole rather than truncated at the default 15 minutes
        fa = A.features(sp, max(900.0, d + 5.0) if d > 890 else 900.0)
        ga = holes(sp) if rec["damaged"] else None
        # 96 staged files decode to a length materially different from what
        # their header claims: Border Patrol says 41 minutes and is 6:10, the
        # Eek-A-Mouse u-neek set throughout is wrong this way. The candidate
        # search runs on the length the AUDIO has, not the length the FILE
        # claims, or those files would be searched against the wrong seconds
        # and never meet the library copy they duplicate
        dec_s = len(fa[0]) / FPS if fa else 0.0
        d_eff = dec_s if dec_s >= 10.0 else d
        seen = []
        for q in range(int(round(d_eff - DTOL)), int(round(d_eff + DTOL)) + 1):
            seen.extend(buckets.get(q, ()))
        for c in cands.get(rel, {}).get("cands", [])[:12]:
            p = c[2] if len(c) > 2 else None
            if p:
                seen.append(p)
        if rec.get("lib"):
            seen.append(rec["lib"])
        # duration is a bad candidate filter for a 27-minute live take (nothing
        # else in the library is 27 minutes long), so whatever shares the title
        # is compared too, whatever its length
        stem = re.sub(r"^\s*\d{1,3}\s*[-._ ]\s*", "",
                      os.path.splitext(os.path.basename(rel))[0])
        for t in {norm(rec["title"] or ""), norm(stem)}:
            seen.extend(by_title.get(t, ()))
        # rank the rest by how many of its words the file shares: two shared
        # words is a real lead, one is noise like "love" or "baby"
        aw = words(rec["title"] or "") | words(stem) | words(rel)
        if aw and len(seen) < 40:
            hits = Counter()
            for w in aw:
                for p in by_word.get(w, ()):
                    hits[p] += 1
            for p, n in hits.most_common(40):
                if n >= 2:
                    seen.append(p)
        seen = [p for p in dict.fromkeys(seen) if p in libd]
        out = {"rel": rel, "title": rec["title"], "album": rec["album"],
               "artist": rec.get("artist", ""), "dur": d, "damaged": rec["damaged"],
               "src_br": rec.get("src_br"), "was": rec["verdict"], "global": rec["score"],
               "tried": len(seen), "lib": "", "fwd": 0.0, "rev": 0.0, "call": "NO-DECODE",
               # the header lied about this file's length: its metadata cannot
               # be trusted either, and a duration comparison against it means
               # nothing
               "hdr_bad": bool(dec_s and d and abs(d - dec_s) > max(6.0, 0.05 * d)),
               # recorded even when nothing could be compared: a row that
               # early-returns still has to say how much audio it holds
               "dec_s": round(dec_s, 1), "win_s": round(win_for(d_eff), 1)}
        if fa is None:
            return out
        win = win_for(d_eff)
        out["win_s"] = win
        best = None                          # highest max(fwd, rev) seen
        for lp in seen:
            # decode the candidate far enough to cover the LONGER of the two:
            # at the 900 s default a 27-minute library track would contribute
            # only its first quarter and the comparison would mean nothing
            need = max(d, libd.get(lp, 0.0)) + 5.0
            fb = A.features(os.path.join(LIB, lp), need if need > 900 else 900.0)
            if fb is None:
                continue
            # library hole masks are not pre-computed (28k files); a damaged
            # library copy can only push a true pair down into BAND, which is
            # reviewed by hand rather than decided, so the error is not silent
            fwd, rev = both(fa, fb, ga, None, win)
            if fwd is None or rev is None:
                continue       # this candidate cannot carry a window this long
            key = max(fwd["mean_best"], rev["mean_best"])
            if best is None or key > best[0]:
                # carry the two envelope lengths with the winning pair: `fb` is
                # the loop variable, so reading it after the loop gives the
                # LAST candidate tried rather than the best one, and every
                # length ratio in the report was wrong because of it
                best = (key, lp, fwd, rev, len(fa[0]), len(fb[0]))
            # an unambiguous SAME needs no further searching
            if min(fwd["mean_best"], rev["mean_best"]) >= 0.95:
                break
        if best is None:
            out["call"] = "NO-CANDIDATE" if seen else "NO-LIBRARY-FILE"
            return out
        _, lp, fwd, rev, nfa, nfb = best
        lr = nfa / max(1, nfb)
        out.update(lib=lp, fwd=round(fwd["mean_best"], 4), rev=round(rev["mean_best"], 4),
                   lr=round(lr, 3), call=call(fwd, rev, lr),
                   # decoded seconds, so a length claim can be checked against
                   # the header rather than being taken on trust
                   dec_s=round(nfa / FPS, 1), lib_dec_s=round(nfb / FPS, 1),
                   ordered=round(min(fwd["ordered"], rev["ordered"]), 3),
                   nwin=min(fwd["nwin"], rev["nwin"]),
                   low_evidence=low_evidence(win, min(fwd["nwin"], rev["nwin"])),
                   holes=round(fwd["holes"], 3))
        return out

    todo = [r for r in rows if r["rel"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"   to classify: {len(todo)}  ({len(done)} already done)", file=sys.stderr)

    n = 0
    with open(OUT, "a", encoding="utf-8") as fh:
        with ThreadPoolExecutor(args.workers) as ex:
            for res in ex.map(work, todo):
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
                if n % 25 == 0:
                    print(f"   {n}/{len(todo)}", file=sys.stderr, flush=True)
    import collections
    print("   ", dict(collections.Counter(
        json.loads(l)["call"] for l in open(OUT, encoding="utf-8"))))


if __name__ == "__main__":
    main()
