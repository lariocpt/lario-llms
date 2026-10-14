"""Calibrate the shape metric per duration class, with the adaptive window.


Truth labels, chosen so they cannot be circular:

  same whole track    -- the global metric's confident duplicates whose DECODED
                         lengths agree within 5 %, i.e. whole copies rather
                         than prefixes (the global score correlates only the
                         shared prefix, so duration alone does not prove that)
  different           -- global score <= 0.30, the far tail of the calibrated
                         "different audio" population

Reported per class: the worst true pair and the best non-pair. The gap between
them is what a threshold has to live in; where the samples are too thin to
trust, the class is left uncalibrated and its files are decided by hand.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_shapecal.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mini_arbiter as A
from mini_arbiter import LIB, STAGE
from mini_cov import compare, good_mask, win_for

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSES = ((0.0, 90.0), (90.0, 180.0), (180.0, 400.0), (400.0, 1e9))
MIN_N = 8            # below this many pairs a class is not calibrated


def main():
    rows = [json.loads(l) for l in open(f"{HERE}/mini-final.jsonl", encoding="utf-8")
            if l.strip() and json.loads(l).get("lib")]

    def decoded(r):
        fa = A.features(os.path.join(STAGE, r["rel"]))
        fb = A.features(os.path.join(LIB, r["lib"]))
        if not fa or not fb:
            return None
        return fa, fb, len(fa[0]) / max(1, len(fb[0]))

    whole, diff = [], []
    for r in rows:
        if r["damaged"]:
            continue
        d = decoded(r)
        if not d:
            continue
        fa, fb, lr = d
        if r["verdict"] == "DUP" and (r["score"] or 0) >= 0.95 and 0.95 <= lr <= 1.05:
            whole.append((r, fa, fb))
        elif r["score"] is not None and r["score"] <= 0.30:
            diff.append((r, fa, fb))
    print(f"   labelled: {len(whole)} whole-track duplicates,"
          f" {len(diff)} definite non-matches")

    print("\n  duration      window  pairs  true dupes                "
          " non-matches            decision gap")
    table = {}
    for lo, hi in CLASSES:
        tw = [(r, fa, fb) for r, fa, fb in whole if lo <= r["dur"] < hi]
        td = [(r, fa, fb) for r, fa, fb in diff if lo <= r["dur"] < hi]
        wins = []

        def work(item):
            r, fa, fb = item
            win = win_for(r["dur"])          # the same rule the real pass uses
            wins.append(win)
            ga = good_mask(os.path.join(STAGE, r["rel"])) if r["damaged"] else None
            f = compare(fa, fb, ga, None, win)
            v = compare(fb, fa, None, ga, win)
            return None if not f or not v or not f["judged"] or not v["judged"] else (
                min(f["mean_best"], v["mean_best"]), max(f["mean_best"], v["mean_best"]))

        out = {}
        for label, group in (("same", tw), ("diff", td)):
            with ThreadPoolExecutor(12) as ex:
                out[label] = sorted(v[0] for v in ex.map(work, group) if v)
        a, b = out["same"], out["diff"]
        name = f"{lo:.0f}-{hi:.0f}s" if hi < 1e9 else f">{lo:.0f}s"
        win = min(wins) if wins else 20.0
        if not a or not b:
            print(f"  {name:12s} {win:5.0f}s  {len(a):3d}/{len(b):3d}"
                  "        too few pairs to calibrate this class")
            continue
        gap = min(a) - max(b)
        table[name] = {"win_s": win, "n_same": len(a), "n_diff": len(b),
                       "same_min": round(min(a), 4), "same_med": round(float(np.median(a)), 4),
                       "diff_max": round(max(b), 4), "diff_med": round(float(np.median(b)), 4),
                       "gap": round(gap, 4), "usable": len(a) >= MIN_N and len(b) >= MIN_N}
        print(f"  {name:12s} {win:5.0f}s  {len(a):3d}/{len(b):3d}"
              f"   min {min(a):.3f} med {np.median(a):.3f}"
              f"   med {np.median(b):.3f} max {max(b):.3f}   {gap:+.3f}"
              f"{'' if table[name]['usable'] else '   TOO FEW PAIRS'}")
    with open(f"{HERE}/mini-shapecal.json", "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1)
    print("\n  gap = worst true duplicate minus best non-match; positive means"
          " the classes do not overlap.")
    print("  thresholds go in the middle of the gap, per class.")
    return 0


if __name__ == "__main__":
    A._cache.update(pickle.load(open(A.CACHE, "rb")))
    print(f"   envelopes: {len(A._cache)}", file=sys.stderr)
    sys.exit(main())
