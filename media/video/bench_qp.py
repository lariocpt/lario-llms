"""Measure a HEVC quality ladder for one file before committing to it.


Encodes a mid-file slice at several qp values and reports size, SSIM and PSNR
against the untouched source, so the choice of qp is a measured trade rather
than a guess. Nothing is written outside the output directory and the source is
never modified.

Remember: -cq does nothing in this ffmpeg build for hevc_nvenc; -rc constqp -qp
is the real control. And `ffmpeg -v error` hides the SSIM/PSNR summary lines,
so these runs deliberately keep the default verbosity and filter stderr.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/bench_qp.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import argparse
import json
import os
import re
import subprocess
import sys

FF = ["ffmpeg", "-nostats", "-y"]


def in_flags(path):
    """MPEG program streams (DVD VOBs) report nothing usable at the default
    probesize and decode zero frames without an error. Same rule as enc_hevc.py."""
    if path.startswith("concat:") or path.lower().endswith((".vob", ".mpg", ".mpeg", ".vts")):
        return ["-probesize", "100M", "-analyzeduration", "200M"]
    return []


def enc(src, qp, out, ss, ln, pix="p010le"):
    cmd = FF + ["-ss", str(ss), "-t", str(ln), *in_flags(src), "-i", src, "-an", "-sn",
                "-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq",
                "-rc", "constqp", "-qp", str(qp), "-pix_fmt", pix, out]
    subprocess.run(cmd, capture_output=True, text=True)
    return os.path.getsize(out) if os.path.exists(out) else 0


def compare(encfile, src, kind, ss, ln):
    """Score the encoded slice against the same span of the source.

    The encode is a slice: its content already STARTS at `ss`, so it is read
    from 0. Only the source is seeked. Seeking both -- which is what this
    originally did -- reads past the end of the slice, ffmpeg exits 0 having
    processed 0 frames, and the 'measurement' is silently nothing at all.
    """
    r = subprocess.run(FF + ["-i", encfile,
                             *in_flags(src), "-ss", str(ss), "-t", str(ln), "-i", src,
                             # framesync (under ssim/psnr) aligns by TIMESTAMP. The
                             # encoded slice starts at PTS 0 while the seeked source
                             # starts at `ss`, so without resetting both pads the
                             # filter duplicates/drops frames to "align" them and
                             # the score is flat nonsense at every qp.
                             "-lavfi", "[0:v]setpts=PTS-STARTPTS,format=yuv420p[a];"
                                       "[1:v]setpts=PTS-STARTPTS,format=yuv420p[b];"
                                       f"[a][b]{kind}=shortest=1",
                             "-an", "-f", "null", "-"], capture_output=True, text=True)
    if "frame=    0" in r.stderr:
        return None
    txt = r.stderr
    # the summary is written at info level by the filter itself, e.g.
    #   [Parsed_ssim_0 @ 0x..] SSIM Y:0.981 U:.. V:.. All:0.979 (16.8dB)
    #   [Parsed_psnr_0 @ 0x..] PSNR y:44.1 u:48.0 v:48.0 average:44.9 ...
    # `-v error` would hide both, and a run that prints nothing has measured
    # nothing -- so keep the default verbosity and read the line out of it.
    if kind == "ssim":
        m = re.search(r"SSIM\b[^\n]*?All:([0-9.]+)", txt) or \
            re.search(r"SIMILARITY:\s*([0-9.]+)", txt)
        return float(m.group(1)) if m else None
    m = re.search(r"PSNR[^\n]*?average:([0-9.]+)", txt, re.I)
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--qp", default="16,18,20,22")
    ap.add_argument("--ss", type=int, default=300)
    ap.add_argument("--len", type=int, default=180)
    ap.add_argument("--tag", default="b")
    ap.add_argument("--pix", default="p010le", help="p010le (house setting) or yuv420p (8-bit)")
    a = ap.parse_args()

    # json, not csv: ffprobe emits format fields in its own order, so a
    # positional csv read silently swaps size and duration and int() explodes.
    j = json.loads(subprocess.run(["ffprobe", "-v", "error", *in_flags(a.src),
                                   "-print_format", "json", "-show_format", a.src],
                                  capture_output=True, text=True).stdout or "{}")
    if "format" not in j:
        sys.exit(f"   ffprobe could not read {a.src}")
    sz = int(j["format"]["size"])
    dur = float(j["format"].get("duration") or 0)
    # bitrate of the slice's worth of source, for a like-for-like saving figure
    print(f"   source {sz/2**30:.2f} GB  {dur/60:.1f} min  "
          f"slice at {a.ss}s for {a.len}s  pix {a.pix}")
    print(f"   {'qp':>3}  {'slice MB':>9}  {'vs src bitrate':>14}  {'SSIM':>8}  {'PSNR':>8}")
    for qp in [int(x) for x in a.qp.split(",")]:
        out = f"/tmp/opencode/{a.tag}.q{qp}.mkv"
        n = enc(a.src, qp, out, a.ss, a.len, a.pix)
        s = compare(out, a.src, "ssim", a.ss, a.len)
        p = compare(out, a.src, "psnr", a.ss, a.len)
        src_slice_bytes = sz * a.len / dur if dur else 0
        ratio = n / src_slice_bytes if src_slice_bytes else 0
        print(f"   {qp:>3}  {n/2**20:>9.1f}  {ratio:>13.0%}  {str(round(s,4)) if s else '?':>8}  "
              f"{str(round(p,1)) if p else '?':>8}", flush=True)
        os.unlink(out)


if __name__ == "__main__":
    main()
