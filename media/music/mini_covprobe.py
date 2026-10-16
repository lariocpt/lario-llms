"""Which window length and how much smoothing actually separates the classes.


The 15 s / unsmoothed version scored 0.6 on files that ARE the same recording:
fine envelope structure decorrelates across a transcode (tiny resampling drift,
encoder padding, loudness processing), while the slow loudness arc survives --
which is exactly why the global full-track number still reads 0.98.

So sweep the two knobs that matter and report the separation for each:
  WIN_S   how long a window is
  SMOOTH  moving-average length applied to the envelope before windowing
Statistic per pair: mean over A's windows of the best match found anywhere in
B. Truth labels come from the calibrated global metric's confident zones, so
the classes are as hard as the cases that will be decided.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/music/mini_covprobe.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
import mini_arbiter as A
from mini_arbiter import HOP, LIB, STAGE

WIN_S = (30.0, 45.0, 60.0, 90.0)
SMOOTH_S = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)


def smooth(env, seconds):
    if not seconds:
        return env
    n = max(1, int(seconds / HOP))
    k = np.ones(n, dtype=np.float64) / n
    return np.convolve(env.astype(np.float64), k, mode="same")


def windows(env, win_frames):
    if len(env) < win_frames:
        return None
    idx = np.arange(0, len(env) - win_frames + 1, max(1, win_frames // 5))
    w = np.stack([env[i:i + win_frames] for i in idx])
    w = w - w.mean(axis=1, keepdims=True)
    n = np.linalg.norm(w, axis=1, keepdims=True)
    n[n < 1e-9] = 1.0
    return w / n


def stat(fa, fb, win_s, smooth_s):
    wa = windows(smooth(fa[0], smooth_s), int(win_s / HOP))
    wb = windows(smooth(fb[0], smooth_s), int(win_s / HOP))
    if wa is None or wb is None or len(wa) < 3 or len(wb) < 3:
        return None
    s = wa @ wb.T
    row = s.max(axis=1)
    return float(np.mean(row)), float(np.median(row)), float(s.max())


def main():
    rows = [json.loads(l) for l in open(f"{WORK}/mini-final.jsonl", encoding="utf-8")
            if l.strip() and json.loads(l).get("lib")]
    same = [r for r in rows if r["verdict"] == "DUP" and (r["score"] or 0) >= 0.95
            and not r["damaged"]]
    diff = [r for r in rows if r["score"] is not None and r["score"] <= 0.30
            and not r["damaged"]]
    dmg = [r for r in rows if r["verdict"] == "DUP" and (r["score"] or 0) >= 0.95
           and r["damaged"]]
    import random
    random.Random(3).shuffle(same)
    random.Random(5).shuffle(diff)
    same, diff, dmg = same[:120], diff[:120], dmg[:40]
    print(f"   same {len(same)}   different {len(diff)}   same-but-damaged"
          f" {len(dmg)}")

    def feats(r):
        return (A.features(os.path.join(STAGE, r["rel"])),
                A.features(os.path.join(LIB, r["lib"])), bool(r["damaged"]))

    pairs = [("same", *f) for f in map(feats, same)] + \
            [("diff", *f) for f in map(feats, diff)] + \
            [("dmg", *f) for f in map(feats, dmg)]

    print(f"\n   window smooth   same recording         |  different audio"
          f"        | damaged     decision gap")
    out = []
    for win_s in WIN_S:
        for sm in SMOOTH_S:
            vals = {"same": [], "diff": [], "dmg": []}
            for label, fa, fb, _isdmg in pairs:
                if fa is None or fb is None:
                    continue
                v = stat(fa, fb, win_s, sm)
                if v:
                    vals[label].append(v[0])
            if min(len(v) for v in vals.values()) < 10:
                continue
            s, d, m = vals["same"], vals["diff"], vals["dmg"]
            gap = min(s) - max(d)
            out.append((gap, win_s, sm, min(s), np.median(s), max(d),
                        np.median(d), min(m), np.median(m)))
    print()
    for gap, win_s, sm, smin, smed, dmax, dmed, mmin, mmed in sorted(
            out, reverse=True)[:14]:
        print(f"   {win_s:5.0f}s {sm:4.2f}s   min {smin:.3f} med {smed:.3f}"
              f"    |  med {dmed:.3f} max {dmax:.3f}  | min {mmin:.3f} med"
              f" {mmed:.3f}   {gap:+.3f}")
    print(f"\n   decision gap = worst true match minus best non-match."
          "  Positive means the two classes do not overlap at all.")
    return 0


if __name__ == "__main__":
    A._cache.update(pickle.load(open(A.CACHE, "rb")))
    print(f"   envelopes: {len(A._cache)}", file=sys.stderr)
    sys.exit(main())
