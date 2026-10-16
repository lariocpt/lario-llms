#!/usr/bin/env python3
"""Measure what a qp actually costs in a SPECIFIC scene, not an average.


The whole-file gate compares one 180 s window. Blade (1998) scored 0.979 and
0.9895 from 60 s slices at t=0 and t=3600 and 0.9365 at t=300 -- the club
scene, strobing lights on 60 fps AI-interpolated footage. Averages hid it; the
single window found it by luck. Either way one sample cannot decide a film.

So: encode the SAME window at several qp and score each window against the
source's own window, aligned the way enc_hevc.metrics() does it (normalise PTS
to zero, then trim, then compare -- an input-side -ss would land each side on
its own keyframe and score motion instead of quality).

  window_quality.py SRC --at 300 3600 --qp 22 24 26 --length 120
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/window_quality.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FF = "ffmpeg"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def encode_window(src, qp, start, length, pix, tmp):
    """Read only start+length seconds, cut the window with trim, encode it."""
    out = Path(tmp) / f"win_{int(start)}_qp{qp}.mkv"
    cmd = [FF, "-nostats", "-v", "error", "-y", "-t", str(start + length), "-i", src,
           "-vf", f"trim=start={start}:end={start + length},setpts=PTS-STARTPTS",
           "-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq",
           "-rc", "constqp", "-qp", str(qp), "-pix_fmt", pix,
           "-an", "-sn", str(out)]
    r = run(cmd)
    return out, r


def compare(src, win, start, length, kind="ssim"):
    """enc pad: the window encode, read from its own 0.
       src pad: the same span picked out of the source by trim."""
    chain = (f"[0:v]setpts=PTS-STARTPTS,format=yuv420p[a];"
             f"[1:v]setpts=PTS-STARTPTS,trim=start={start}:end={start + length},"
             f"setpts=PTS-STARTPTS,format=yuv420p[b];[a][b]{kind}=shortest=1")
    r = run([FF, "-nostats", "-v", "error", "-t", str(length), "-i", str(win),
             "-t", str(start + length), "-i", src, "-lavfi", chain, "-an", "-f", "null", "-"])
    m = re.search(r"All:(\s*[0-9.]+|inf)", r.stderr) or re.search(r"average:([0-9.]+|inf)", r.stderr)
    if not m:
        return None
    v = m.group(1)
    return float("inf") if v == "inf" else float(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--at", type=float, nargs="+", default=[300.0])
    ap.add_argument("--qp", type=int, nargs="+", default=[22, 24, 26])
    ap.add_argument("--length", type=float, default=120.0)
    ap.add_argument("--pix", default="p010le")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    src = args.src
    dur = probe_duration(src)
    if not dur:
        sys.exit(f"cannot read {src}")
    rows = []
    print(f"   source {Path(src).stat().st_size / 2**30:.2f} GB  {dur / 60:.0f} min")
    for start in args.at:
        if start + args.length > dur:
            print(f"   window at {start:.0f}s runs past the end, skipped")
            continue
        print(f"\n   --- window at {start:.0f}s for {args.length:.0f}s ---")
        print("      qp      MB    vs src bitrate      SSIM      PSNR")
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            for qp in args.qp:
                win, r = encode_window(src, qp, start, args.length, args.pix, tmp)
                if not win.exists():
                    print(f"      {qp:3}  encode failed: {r.stderr.strip()[:120]}")
                    continue
                mb = win.stat().st_size / 2**20
                # the source's own bitrate for that span, as the size yardstick
                src_span = Path(src).stat().st_size * args.length / dur / 2**20
                s = compare(src, win, start, args.length, "ssim")
                p = compare(src, win, start, args.length, "psnr")
                print(f"      {qp:3}  {mb:7.1f}  {100 * mb / src_span:11.0f}%"
                      f"      {s if s is None else round(s, 4)}   {round(p, 1) if p else '-'}")
                rows.append({"start": start, "qp": qp, "mb": round(mb, 1),
                             "pct_src_bitrate": round(100 * mb / src_span, 1),
                             "ssim": s, "psnr": p})
                win.unlink()
    if args.json:
        Path(args.json).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    ok = [r for r in rows if r["ssim"] and r["ssim"] >= 0.97]
    if ok:
        best = min(ok, key=lambda r: r["mb"])
        print(f"\n   clearing 0.97 in every sampled window? pick the cheapest: qp{best['qp']} "
              f"at {best['start']:.0f}s = {best['mb']} MB ({best['pct_src_bitrate']}% of source bitrate)")
    else:
        print("\n   no qp sampled clears 0.97 in these windows -- widen the range")


if __name__ == "__main__":
    main()
