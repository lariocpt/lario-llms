"""Arbitrate the cases the 30-second windows cannot settle.

The windowed envelope metric was calibrated on library-vs-library pairs
(different audio <=0.55, same recording >=0.93). Source files are 32-320 k
MP3 against library FLAC, and a wider quality gap can pull a true match into
the ambiguous band for reasons that mean nothing -- so ambiguous cases are
retested on the WHOLE track, which is ~10x more evidence, and the threshold
for that measure is calibrated on pairs whose truth is already known.

Nothing is decided here that is not written down with its score.
"""
import json
import os
import pickle
import re
import sqlite3
import subprocess
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from paths import STAGE
from paths import LIB
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = f"{HERE}/fullenv-cache.pkl"
SR = 8000
HOP = 0.02
LAG = 25.0  # seconds of alignment slack


def norm(s):
    return re.sub(r"[^0-9a-z\u00c0-\uffff]+", "", (s or "").casefold())


def dec_full(path, limit=900.0):
    """Whole track, mono at SR. Cached on disk by path."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-t", f"{limit}", "-ac", "1",
         "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, timeout=600)
    if r.returncode != 0 or len(r.stdout) < SR * 4 * 10:
        return None
    a = np.nan_to_num(np.frombuffer(r.stdout, dtype=np.float32))
    return a


_cache = {}
_lock = threading.Lock()


def features(path, limit=900.0):
    """Envelope + onset features. limit is how much of the file to decode: the
    default covers normal tracks, but a 27-minute live take must be decoded to
    its full length or a comparison against it sees only the first 15 minutes.
    Entries decoded with a non-default limit get their own cache key so they
    cannot be served by (or shadow) the truncated one."""
    key = path if limit == 900.0 else (path, limit)
    with _lock:
        if key in _cache:
            return _cache[key]
    a = dec_full(path, limit)
    out = None
    if a is not None and len(a) > SR * 10:
        n = max(1, int(SR * HOP))
        m = len(a) // n
        e = np.sqrt((a[:m * n].reshape(m, n) ** 2).mean(axis=1)).astype(np.float32)
        # zero-hole mask: a damaged stretch carries no information, and a run of
        # zeros inflates correlation with anything quiet, so mark those frames
        hole = (np.abs(a[:m * n].reshape(m, n)) < 1e-6).mean(axis=1) > 0.5
        e = np.where(hole, 0.0, e)
        e = e - e.mean()
        ne = float(np.linalg.norm(e))
        on = np.maximum(np.diff(e), 0).astype(np.float32)
        on = on - on.mean()
        no = float(np.linalg.norm(on))
        if ne > 1e-9 and no > 1e-9:
            out = (e / ne, on / no)
    with _lock:
        _cache[key] = out
    return out


def load():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    return {}


def save(cache):
    tmp = CACHE + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(cache, fh, protocol=4)
    os.replace(tmp, CACHE)


def corr_max(x, y, lag_frames):
    n = min(len(x), len(y))
    if n < 400:
        return -1.0
    x, y = x[:n], y[:n]
    L = 1
    while L < n + lag_frames:
        L *= 2
    c = np.fft.irfft(np.fft.rfft(x.astype(np.float64), L)
                     * np.conj(np.fft.rfft(y.astype(np.float64), L)), L)
    d = float(np.linalg.norm(x)) * float(np.linalg.norm(y)) + 1e-12
    pos = np.abs(c[:lag_frames + 1]) / d
    neg = np.abs(c[L - lag_frames:]) / d
    return float(np.max(np.concatenate([pos, neg])))


def score(fa, fb):
    if fa is None or fb is None:
        return -1.0
    lag = int(LAG / HOP)
    return max(corr_max(fa[0], fb[0], lag), corr_max(fa[1], fb[1], lag))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    a = ap.parse_args()
    cache = load()
    _cache.clear()
    _cache.update(cache)

    if a.calibrate:
        # truth labels from the windowed metric's confident zones
        pairs = json.load(open(f"{HERE}/mini-envcal.json", encoding="utf-8"))
        same = [p for p in pairs if p[0] >= 0.93]
        diff = [p for p in pairs if p[0] <= 0.35]
        for label, group in (("same recording (windowed >=0.93)", same[:40]),
                             ("different audio (windowed <=0.35)", diff[:40])):
            out = []
            def work(p):
                return score(features(os.path.join(LIB, p[1])), features(os.path.join(LIB, p[5])))
            with ThreadPoolExecutor(12) as ex:
                out = list(ex.map(work, group))
            out = [v for v in out if v >= 0]
            out.sort()
            print(f"\n{label}: n={len(out)}")
            if out:
                print(f"   min {out[0]:.4f}  p25 {out[len(out)//4]:.4f}"
                      f"  median {out[len(out)//2]:.4f}  max {out[-1]:.4f}")
                print(f"   lowest 6: {['%.3f' % v for v in out[:6]]}")
        save(dict(_cache))
        return


if __name__ == "__main__":
    main()
