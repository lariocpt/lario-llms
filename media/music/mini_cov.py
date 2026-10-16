"""Second opinion for the ambiguous band, calibrated by mini_covprobe.py.

The global full-track score is one number for a whole file, and it is dragged
down by things that do not mean the recording differs: silence padding, a
different start offset, a truncated end, a damaged stretch, or a 128k source
against a FLAC. This compares SHAPE LOCALLY instead: both files are smoothed
(1 s) and cut into 90 s windows, every window of A is matched against every
window of B, and the statistic is how well A's windows find themselves in B.

  mean_best  -- mean over A's windows of the best match found in B
                (this is what the probe calibrated: same recording never below
                 0.839, different audio never above 0.581 on 120+82 pairs of
                 known truth, so the classes do not overlap)
  ordered    -- longest increasing run of matched positions / window count:
                same material in the same order. A megamix of the same
                snippets scores high on mean_best but low here.
  holes      -- fraction of A that is a literal-zero run (destroyed audio);
                those windows are dropped, never counted as a mismatch
  len_ratio  -- len(A)/len(B): a short file that fits inside a long one is
                CONTAINED (a track inside a mix), not a duplicate of it

Windows shorter than one window length cannot be judged: they come back None
and stay undecided rather than being forced.
"""
import json
import os
import pickle
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORK      # evidence root: config.MUSIC_WORK, env LARIO_MUSIC_WORK
os.makedirs(WORK, exist_ok=True)   # one evidence root for the whole pass
import mini_arbiter as A
from mini_arbiter import HOP, LIB, STAGE

WIN_S = 90.0
SMOOTH_S = 1.0
SAME_AT = 0.80        # probe: worst true match 0.839
DIFF_AT = 0.55        # probe: best non-match 0.581
CONTAINED = 0.60      # below this length ratio a match means "inside" not "same"


def good_mask(path):
    """1.0 for frames holding real audio, 0.0 inside a literal-zero run."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-t", "900", "-ac", "1",
         "-ar", str(A.SR), "-f", "f32le", "-"], capture_output=True, timeout=600)
    if r.returncode != 0 or len(r.stdout) < A.SR * 4 * 10:
        return None
    a = np.nan_to_num(np.frombuffer(r.stdout, dtype=np.float32))
    n = max(1, int(A.SR * HOP))
    m = len(a) // n
    zero = (np.abs(a[:m * n].reshape(m, n)) < 1e-6).mean(axis=1) > 0.5
    return (1.0 - zero).astype(np.float32)


def smooth(env):
    n = max(1, int(SMOOTH_S / HOP))
    k = np.ones(n, dtype=np.float64) / n
    return np.convolve(np.asarray(env, dtype=np.float64), k, mode="same")


def windows(env, good, win_s=None):
    """Mean-removed, unit-length windows, damaged ones zeroed and flagged."""
    win = int((win_s or WIN_S) / HOP)
    if env is None or len(env) < win:
        return None, None
    good = (np.ones(len(env), dtype=np.float64) if good is None else
            np.asarray(good, dtype=np.float64))
    if len(good) < len(env):
        good = np.concatenate([good, np.ones(len(env) - len(good))])
    good = good[:len(env)]
    idx = np.arange(0, len(env) - win + 1, max(1, win // 3))
    w = np.stack([env[i:i + win] for i in idx])
    g = np.stack([good[i:i + win] for i in idx])
    damaged = g.mean(axis=1) < 0.7          # >30% of the window is a hole
    w = w - w.mean(axis=1, keepdims=True)
    n = np.linalg.norm(w, axis=1, keepdims=True)
    n[n < 1e-9] = 1.0
    return np.where(damaged[:, None], 0.0, w / n), damaged


def lis_run(positions):
    if len(positions) == 0:
        return 0
    lis = np.ones(len(positions), dtype=int)
    for i in range(1, len(positions)):
        prev = np.where(positions[:i] < positions[i])[0]
        if len(prev):
            lis[i] = lis[prev].max() + 1
    return int(lis.max())


def win_for(dur):
    """Window length for a file: about half of it, capped at the calibrated
    90 s. The floor must stay below any real file: a 20 s floor made every
    track under 40 s unjudgeable BY CONSTRUCTION, because a file shorter than
    one window cannot be compared at all. Comparisons on a short window are
    marked low-evidence instead -- see low_evidence() -- rather than silently
    refused or trusted."""
    return max(5.0, min(WIN_S, (dur or 0.0) / 2.0))


def low_evidence(win_s, nwin):
    """True when the comparison is too coarse to decide anything on its own:
    the calibration was measured on 90 s windows, so short windows and files
    that only yield a couple of windows are not covered by those thresholds.
    Such a row falls through to the metadata check instead of being called."""
    return win_s < 20.0 or (nwin or 0) < 3


def compare(fa, fb, ga=None, gb=None, win_s=None):
    if fa is None or fb is None:
        return None
    wa, da = windows(smooth(fa[0]), ga, win_s)
    wb, db = windows(smooth(fb[0]), gb, win_s)
    if wa is None or wb is None:
        return None
    usable = ~da
    if not usable.any():
        return {"mean_best": 0.0, "ordered": 0.0, "holes": float(da.mean()),
                "len_ratio": len(fa[0]) / max(1, len(fb[0])), "nwin": int(usable.sum()),
                "judged": False}
    s = wa @ wb.T
    if db is not None:
        s[:, db] = 0.0
    best = s.max(axis=1)[usable]
    matched = usable & (s.max(axis=1) >= SAME_AT)
    return {
        "mean_best": float(best.mean()),
        "med_best": float(np.median(best)),
        "worst_best": float(best.min()),
        "ordered": lis_run(s.argmax(axis=1)[matched]) / max(1, int(usable.sum())),
        "holes": float(da.mean()),
        "len_ratio": len(fa[0]) / max(1, len(fb[0])),
        "nwin": int(usable.sum()),
        "judged": int(usable.sum()) >= 2,
    }


def decide(v):
    """Verdict from the calibrated bands; the middle stays undecided."""
    if v is None or not v["judged"]:
        return "NOT-JUDGED"
    if v["mean_best"] >= SAME_AT:
        return "CONTAINED" if v["len_ratio"] < CONTAINED else "SAME"
    if v["mean_best"] <= DIFF_AT:
        return "DIFFERENT"
    return "BAND"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="re-verify the calibration on pairs of known truth")
    ap.add_argument("--statuses", default="UNDECIDED,NO-COMPARISON")
    ap.add_argument("--out", default=f"{WORK}/mini-cov.jsonl")
    args = ap.parse_args()

    if os.path.exists(A.CACHE):
        with open(A.CACHE, "rb") as fh:
            A._cache.update(pickle.load(fh))
        print(f"   envelopes loaded: {len(A._cache)}", file=sys.stderr)

    rows = [json.loads(l) for l in open(f"{WORK}/mini-final.jsonl", encoding="utf-8")
            if l.strip()]

    if args.check:
        same = [r for r in rows if r["verdict"] == "DUP" and (r["score"] or 0) >= 0.95]
        diff = [r for r in rows if r["score"] is not None and r["score"] <= 0.30]
        for label, group in (("same recording", same[:200]), ("different audio", diff)):
            def work(r):
                sp = os.path.join(STAGE, r["rel"])
                return compare(A.features(sp), A.features(os.path.join(LIB, r["lib"])),
                               good_mask(sp) if r["damaged"] else None)
            with ThreadPoolExecutor(12) as ex:
                vals = [v for v in ex.map(work, group) if v and v["judged"]]
            mb = sorted(v["mean_best"] for v in vals)
            print(f"\n   {label}: n={len(mb)}  min {mb[0]:.3f}"
                  f"  p25 {mb[len(mb)//4]:.3f}  median {mb[len(mb)//2]:.3f}"
                  f"  max {mb[-1]:.3f}")
            tally = {}
            for d in ("SAME", "CONTAINED", "BAND", "DIFFERENT", "NOT-JUDGED"):
                tally[d] = sum(1 for v in vals if decide(v) == d)
            print(f"      this pass would call: {json.dumps(tally, sort_keys=True)}")
        return

    want = set(args.statuses.split(","))
    todo = [r for r in rows if r["verdict"] in want]
    cands = json.load(open(f"{WORK}/mini-cands.json", encoding="utf-8"))
    print(f"   retesting {len(todo)} files", file=sys.stderr)

    def lib_of(r):
        out, seen = [], set()
        if r.get("lib"):
            out.append(r["lib"])
            seen.add(r["lib"])
        for c in cands.get(r["rel"], {}).get("cands", [])[:12]:
            p = c[2] if len(c) > 2 else None
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def work(r):
        sp = os.path.join(STAGE, r["rel"])
        fa = A.features(sp)
        ga = good_mask(sp) if r["damaged"] else None
        best = None
        for lp in lib_of(r):
            v = compare(fa, A.features(os.path.join(LIB, lp)), ga)
            if v and (best is None or v["mean_best"] > best[1]["mean_best"]):
                best = (lp, v)
        return {"rel": r["rel"], "title": r["title"], "album": r["album"],
                "artist": r.get("artist", ""), "dur": r["dur"],
                "global": r["score"], "verdict": r["verdict"],
                "damaged": r["damaged"], "lib": best[0] if best else "",
                "cov": best[1] if best else None,
                "call": decide(best[1]) if best else "NOT-JUDGED",
                "tried": len(lib_of(r))}

    n = 0
    with open(args.out, "w", encoding="utf-8") as fh:
        with ThreadPoolExecutor(10) as ex:
            for res in ex.map(work, todo):
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                n += 1
                if n % 20 == 0:
                    print(f"   {n}/{len(todo)}", file=sys.stderr, flush=True)
    print(f"   wrote {n} -> {args.out}", file=sys.stderr)
    import collections
    print("   ", dict(collections.Counter(
        json.loads(l)["call"] for l in open(args.out, encoding="utf-8"))))


if __name__ == "__main__":
    main()
