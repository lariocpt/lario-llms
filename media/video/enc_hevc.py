"""HEVC re-encode, quality-gated by measurement instead of by eye.


The rule that keeps this honest: a source is only replaced once its encode has
(a) opened, (b) matched the source's duration, resolution, sample aspect and
audio/subtitle stream counts, (c) decoded end to end with no errors, (d) scored
at least MIN_SSIM against the source on a mid-file 180-second slice, and (e)
beaten the source by MIN_GAIN on size. Anything failing any gate keeps its
source and the encode is deleted. A re-encode that buys nothing is only
generation loss, and an encode that saves size by looking worse is a loss too.

SSIM/PSNR are measured on a slice, not the whole title, because the whole point
is to decide before deleting; the slice is taken 5 minutes in, which in these
titles is ordinary footage rather than the opening credits.

Three things this build of ffmpeg (N9.0.2) does that will bite you:

  * it SILENTLY IGNORES -cq for hevc_nvenc -- four different values produced
    byte-identical files. The knob that takes effect is `-rc constqp -qp N`.
  * `-v error` suppresses the psnr/ssim summary lines along with the errors, so
    a measurement run that prints nothing has not measured anything. Keep the
    default log level and read stderr, then filter.
  * psnr and ssim cannot share one filter chain when both need a format fix;
    run them as separate invocations.

Anamorphic sources are the other trap. Blackadder is stored at 704x574 with a
sample aspect of about 374:351 -- a 4:3 picture. An encoder that flattens SAR
to 1:1 shows every episode squashed sideways, and it will still "pass" a
resolution check because 704x574 is unchanged. SAR and DAR are compared here.

Audio and subtitles are copied, never re-encoded; metadata and chapters carried
over. Resolution and frame rate are never changed -- downscaling a 4K master to
save space is a decision for the owner, not for the encoder.

    usage: enc_hevc.py [--root DIR]... [--log PATH] [--qp N] [--min-gain F]
                      [--min-ssim F] [--drop-audio LAST|NONE] [--no-ssim] [name ...]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/video/enc_hevc.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from fractions import Fraction

MIN_SSIM_DEFAULT = 0.975
SLICE_AT, SLICE_LEN = 300, 180
# A discarded letterbox bar must be black, not merely dark: 16/255 sits below
# black-point plus grain, and 95% of sampled frames is high enough that a few
# genuinely dark shots cannot convince the gate to eat picture.
BAR_LUMA_MAX, BAR_FRAME_FRAC = 16, 0.95


def probe(path):
    j = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", *in_flags(path), "-print_format", "json",
         "-show_streams", "-show_format", path],
        capture_output=True, text=True).stdout or "{}")
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    a = [s for s in j["streams"] if s["codec_type"] == "audio"]
    return {"codec": v.get("codec_name"), "w": v.get("width"), "h": v.get("height"),
            "sar": v.get("sample_aspect_ratio") or "1:1", "dar": v.get("display_aspect_ratio") or "",
            "fps": v.get("avg_frame_rate"), "pix": v.get("pix_fmt"),
            "dur": float(j.get("format", {}).get("duration") or 0),
            "br": int(j.get("format", {}).get("bit_rate") or 0),
            "n_a": len(a), "n_s": sum(1 for s in j["streams"] if s["codec_type"] == "subtitle"),
            "aud_bytes": sum(int(s.get("bit_rate") or 0) for s in a) * float(
                j.get("format", {}).get("duration") or 0) / 8}


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def in_flags(path):
    """Input flags a given source needs before it will describe itself honestly.

    MPEG program streams (a DVD's VOBs, or several of them joined with ffmpeg's
    concat: URL) report no useful stream parameters at the default probesize:
    ffprobe returns 0-channel AC3 and no duration, and ffmpeg decodes zero
    frames without ever printing an error. Ask for more probe bytes and the same
    file yields a clean 25 fps. Anything that touches such a source -- probe,
    encode, bar detection, SSIM -- must pass these or its result is meaningless.
    """
    if path.startswith("concat:") or path.lower().endswith((".vob", ".mpg", ".mpeg", ".vts")):
        return ["-probesize", "100M", "-analyzeduration", "200M"]
    return []


def size_of(path):
    """Bytes of an input, including the concat: pseudo-URL a DVD title is read as."""
    if path.startswith("concat:"):
        return sum(os.path.getsize(p) for p in path[len("concat:"):].split("|")
                   if os.path.exists(p))
    return os.path.getsize(path)


def encode(src, tmp, qp, drop_audio_last, vf=None, set_dar=None):
    cmd = ["ffmpeg", "-v", "error", "-nostats", "-y", *in_flags(src), "-i", src,
           "-map", "0:v:0"]
    if drop_audio_last == "LAST" and probe(src)["n_a"] > 1:
        cmd += ["-map", "0:a:0"]          # keep the primary track only
    else:
        cmd += ["-map", "0:a?"]
    cmd += ["-map", "0:s?"]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq",
            "-rc", "constqp", "-qp", str(qp), "-pix_fmt", "p010le", "-tag:v", "hvc1",
            "-c:a", "copy", "-c:s", "copy", "-map_metadata", "0", "-map_chapters", "0"]
    if set_dar:
        # telling the encoder what the picture is meant to look like, because the
        # source's own metadata lied (PAL anamorphic discs)
        cmd += ["-fps_mode", "cfr", "-aspect", set_dar]
    cmd += [tmp]
    t0 = time.time()
    r = run(cmd)
    return time.time() - t0, r.stderr.strip()


def metrics(src, enc, src_vf="", enc_vf="", from_start=False):
    """SSIM and PSNR of the encode against the source, on the same slice.

    Both are forced to 8-bit yuv420p for the comparison: the encode is 10-bit,
    the source is 8-bit, and comparing after truncation is the standard way to
    ask "does this look like the original". src_vf/enc_vf must line the two up
    when the encode cropped or de-flagged timestamps -- comparing a cropped
    frame against an uncropped one scores garbage, not quality.

    from_start compares from 0 rather than 5 minutes in, because ffmpeg cannot
    seek reliably inside a DVD read through a concat: URL. At tens of times
    realtime a ten-minute measured comparison costs seconds, so taking the honest
    path costs nothing.
    """
    ssim = psnr = None
    ef = (enc_vf + ",") if enc_vf else ""
    rf = (src_vf + ",") if src_vf else ""
    # Seeking 5 minutes in and reading past the END of the file is the classic
    # way to "measure" nothing at all: ffmpeg exits 0, prints no summary, and an
    # unmeasured encode would otherwise sail through the quality gate. Short
    # extras (interviews, featurettes) are compared from the start instead.
    dur = 0.0
    try:
        dur = probe(src)["dur"]
    except (KeyError, ValueError):
        pass
    if dur and dur < SLICE_AT + SLICE_LEN:
        from_start = True
    # HOW to take the measurement window. An input-side `-ss` is a SEEK, i.e. a
    # jump to the nearest keyframe, and two encodes of one movie have different
    # keyframe grids -- so the two sides start at different frames, framesync
    # pairs them anyway, and the score measures motion instead of quality (that
    # is how a clean 1080p encode scored 0.9162 and a good 4K one 0.9365).
    # `-ss` after `-i` cannot help: with two inputs ffmpeg reads it as an option
    # of the OUTPUT, not of one input. So bound the read with `-t` from the top
    # and let `trim` pick the window on timestamps. Exact, and still only decodes
    # A+L seconds rather than the whole file.
    at = [] if from_start else ["-t", str(SLICE_AT + SLICE_LEN)]
    # `trim` cuts on ABSOLUTE timestamps, and the two files do not share a
    # starting one: an NVENC mkv began at PTS 83 (0.083s, two frames) while its
    # source began at 0, so the two "same" windows were two frames apart and
    # scored 22.7 dB of pure motion. Normalise each pad to zero BEFORE trimming,
    # and the window means the same span of pictures on both sides.
    norm = "setpts=PTS-STARTPTS,"
    win = norm + ("" if from_start else f"trim=start={SLICE_AT}:end={SLICE_AT + SLICE_LEN},")
    for kind in ("ssim", "psnr"):
        r = run(["ffmpeg", "-nostats", *at, "-i", enc,
                 *in_flags(src), *at, "-i", src,
                 # ssim/psnr are built on framesync, which aligns the two pads by
                 # TIMESTAMP, not by frame order. Two files of the same movie can
                 # start at different PTS bases (container start_time, encoder
                 # delay), and framesync then silently duplicates and drops
                 # frames to line them up -- the score wanders with motion and has
                 # nothing to do with quality (this rejected a good 4K encode at
                 # "SSIM 0.9365" and scored a clean 1080p one at 0.83). Reset both
                 # pads to zero and stop at the shorter side, and the number means
                 # what it says.
                 "-lavfi", f"[0:v]{win}{ef}setpts=PTS-STARTPTS,format=yuv420p[a];"
                           f"[1:v]{win}{rf}setpts=PTS-STARTPTS,format=yuv420p[b];"
                           f"[a][b]{kind}=shortest=1",
                 "-f", "null", "-"])
        txt = r.stderr
        if kind == "ssim":
            m = re.search(r"SSIM\b[^\n]*?All:([0-9.]+)", txt) or \
                re.search(r"SIMILARITY:\s*([0-9.]+)", txt)
            ssim = float(m.group(1)) if m else None
        else:
            m = re.search(r"PSNR[^\n]*?average:([0-9.]+)", txt, re.I)
            psnr = float(m.group(1)) if m else None
    return ssim, psnr


def decodes_clean(path, extra=()):
    r = run(["ffmpeg", "-v", "error", "-nostats", *extra, "-i", path,
             "-map", "0:v:0", "-f", "null", "-"])
    return r.returncode == 0 and not r.stderr.strip(), r.stderr.strip()[:200]


def band_black_fraction(path, crop_expr, frames=45):
    """How often a strip of the picture is black, measured in that strip alone.

    The strip is named by a crop expression, so this can ask about the top rows,
    the bottom rows or a side edge. Reading the whole frame's minimum instead --
    which is what an earlier version of this did -- reports pure black for any
    frame containing one dark pixel, i.e. most of cinema, and would call ordinary
    full-frame footage letterboxed and crop real picture away.

    metadata=print logs at info level, so this must NOT pass -v error: it would
    read nothing and report "no bars", silently.
    """
    r = run(["ffmpeg", "-nostats", *in_flags(path), "-ss", str(SLICE_AT), "-t", str(frames),
             "-i", path,
             "-vf", f"{crop_expr},format=gray,signalstats,"
                    "metadata=print:key=lavfi.signalstats.YMAX",
             "-an", "-sn", "-f", "null", "-"])
    vals = [float(x.split("=")[1]) for x in r.stderr.replace("\n", " ").split() if "YMAX=" in x]
    if len(vals) < 10:
        return 0.0
    return sum(1 for v in vals if v <= BAR_LUMA_MAX) / len(vals)


def cropdetect(path, frames=250):
    """A crop rectangle that two independent measurements agree on, else None.

    cropdetect alone is not safe to act on: it reports the largest rectangle
    containing no black, so a run of dark shots convinces it to eat real picture.
    So let it propose the bars, then read the luma of exactly the rows it wants
    to discard and crop only what is demonstrably black in BAR_FRAME_FRAC of the
    sampled frames. Everything it wanted to take that turns out not to be black
    is kept.

    Note this build logs its verdict as `crop:W:H:X:Y`, not `crop=W:H:X:Y`; a
    parser written against the other form matches nothing and silently reports
    "no crop needed".
    """
    full = probe(path)
    fw, fh = full["w"], full["h"]
    r = run(["ffmpeg", "-nostats", *in_flags(path), "-ss", str(SLICE_AT), "-t", str(frames),
             "-i", path,
             "-vf", "cropdetect=24:2:0", "-an", "-sn", "-f", "null", "-"])
    cands = [tuple(int(g) for g in m) for m in
             re.findall(r"crop:(\d+):(\d+):(\d+):(\d+)", r.stderr)]
    if not cands:
        return None
    cands.sort()
    w, h, x, y = cands[len(cands) // 2]        # median: one odd frame cannot decide
    want = {"top": (y, f"crop=iw:{y}:0:0"),
            "bottom": (fh - y - h, f"crop=iw:{fh - y - h}:0:{y + h}"),
            "left": (x, f"crop={x}:ih:0:0"),
            "right": (fw - x - w, f"crop={fw - x - w}:ih:0:{fw - w}")}
    cut = {side: px for side, (px, expr) in want.items()
           if px >= 2 and band_black_fraction(path, expr, max(15, frames // 5)) >= BAR_FRAME_FRAC}
    if not cut:
        return None
    cw, ch = fw - cut.get("left", 0) - cut.get("right", 0), fh - cut.get("top", 0) - cut.get("bottom", 0)
    if (cw, ch) == (fw, fh) or cw < 64 or ch < 64:
        return None
    return cw, ch, cut.get("left", 0), cut.get("top", 0)


def as_dar(text):
    """A display-aspect string as a Fraction, so 40:27 and 1.48:1 can be compared."""
    from fractions import Fraction
    try:
        a, b = str(text).split(":")
        return Fraction(int(a), int(b))
    except (ValueError, AttributeError, ZeroDivisionError):
        return None


def has_setpts(path):
    """True when the video carries setpts drop/hide flags (PAL DVD menus, some
    film-origin rips). They survive a stream copy and make players skip frames
    against a 25fps container, so such a disc must be re-timed, not copied."""
    r = run(["ffmpeg", "-v", "error", *in_flags(path), "-ss", str(SLICE_AT), "-t", "60", "-i", path,
             "-vf", "setpts=NOPTS", "-an", "-sn", "-f", "null", "-"])
    return "setpts" in r.stderr.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", default=[])
    ap.add_argument("--src-file", action="append", default=[],
                    help="one explicit input (a file, or a concat: URL for a DVD title)")
    ap.add_argument("--out", default=None,
                    help="destination for --src-file; without it the source is replaced in place")
    ap.add_argument("--log", required=True)
    ap.add_argument("--qp", type=int, default=16)
    ap.add_argument("--min-gain", type=float, default=0.15)
    ap.add_argument("--min-ssim", type=float, default=MIN_SSIM_DEFAULT)
    ap.add_argument("--drop-audio", choices=["LAST", "NONE"], default="NONE")
    ap.add_argument("--crop", choices=["LETTERBOX", "NONE"], default="NONE",
                    help="crop away black letterbox bars when the source carries them")
    ap.add_argument("--crop-rect", default=None,
                    help="explicit WxH+X+Y crop, for sources ffmpeg cannot seek "
                         "reliably enough to measure (a DVD read via concat:)")
    ap.add_argument("--set-dar", default=None,
                    help="force a display aspect ratio (PAL discs whose metadata lies)")
    ap.add_argument("--setpts", choices=["AUTO", "NONE"], default="NONE",
                    help="strip setpts drop/hide flags by re-timing to CFR")
    ap.add_argument("--no-ssim", action="store_true")
    ap.add_argument("--metrics-from-start", action="store_true",
                    help="compare from 0, not 5 minutes in (DVD concat inputs cannot seek)")
    ap.add_argument("only", nargs="*")
    a = ap.parse_args()
    if a.out and os.path.exists(a.out):
        sys.exit(f"   refusing to overwrite an existing destination: {a.out}")
    if a.out and not a.src_file:
        sys.exit("   --out only makes sense with --src-file")

    files = list(a.src_file)
    for d in a.root:
        for r, _x, fs in os.walk(d, onerror=lambda e: None):
            for f in sorted(fs):
                if f.endswith(".mkv") and ".hevc." not in f:
                    files.append(os.path.join(r, f))
    if a.only:
        files = [f for f in files if any(o.lower() in f.lower() for o in a.only)]

    done = set()
    if os.path.exists(a.log):
        for l in open(a.log, encoding="utf-8"):
            rec = json.loads(l)
            if rec.get("adopted"):
                done.add(rec["src"])
    print(f"   {len(files)} candidates, qp{a.qp}, min SSIM {a.min_ssim}, "
          f"min gain {a.min_gain:.0%}, drop_audio={a.drop_audio}", flush=True)

    for path in files:
        name = os.path.basename(path)[:50]
        if path in done:
            print(f"   SKIP     {name}: already encoded", flush=True)
            continue
        before = probe(path)
        if before["codec"] in ("hevc", "av1"):
            print(f"   SKIP     {name}: already {before['codec']}", flush=True)
            continue
        old = size_of(path)
        print(f"   ENCODE   {name}\n            {old/2**30:.2f} GB "
              f"{before['w']}x{before['h']} SAR {before['sar']} DAR {before['dar']} "
              f"{before['br']/1e6:.1f} Mbps "
              f"{before['dur']/60:.0f} min  audio {before['n_a']} trk "
              f"({before['aud_bytes']/2**30:.2f} GB)", flush=True)

        # Geometry decisions happen here, once, and are then asserted of the
        # output. Cropping black bars is free; re-tagging an aspect ratio the
        # disc got wrong is free; neither is allowed to drift silently.
        vf, cd = [], None
        if a.crop_rect:
            w, h, x, y = (int(g) for g in re.match(
                r"(\d+)x(\d+)\+(\d+)\+(\d+)$", a.crop_rect).groups())
            cd = (w, h, x, y)
            vf.append(f"crop={w}:{h}:{x}:{y}")
            print(f"      explicit crop {w}x{h}+{x}+{y}", flush=True)
        elif a.crop == "LETTERBOX":
            cd = cropdetect(path)
            if cd:
                vf.append(f"crop={cd[0]}:{cd[1]}:{cd[2]}:{cd[3]}")
                print(f"      letterboxed -> cropping to {cd[0]}x{cd[1]} +{cd[2]}+{cd[3]}",
                      flush=True)
        if a.setpts == "AUTO" and has_setpts(path):
            vf.append("setpts=NOPTS")
            print("      setpts drop/hide flags present -> re-timing to CFR", flush=True)
        vf = ",".join(vf) or None

        dst = a.out or path
        tmp = os.path.splitext(dst)[0] + ".hevc.mkv"
        if a.out:
            # the encoder opens the tmp path itself, so the destination directory
            # has to exist BEFORE it runs, not at adoption time
            os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        exp_wh = (cd[0], cd[1]) if cd else (before["w"], before["h"])
        # Cropping pixels does not change how a pixel is DISPLAYED: the SAR
        # survives and the DAR narrows by whatever height is left. The earlier
        # version of this forced SAR 1:1 after a crop, which stretches an
        # anamorphic source -- the exact defect this pipeline exists to avoid.
        if a.set_dar:
            exp_dar, exp_sar = as_dar(a.set_dar), "1:1"
        elif cd:
            num, den = (int(v) for v in (before["sar"] or "1:1").split(":"))
            exp_dar, exp_sar = Fraction(cd[0] * num, cd[1] * den), before["sar"]
        else:
            exp_dar, exp_sar = as_dar(before["dar"]), before["sar"]
        if a.set_dar:
            print(f"      forcing DAR {a.set_dar} (source metadata said "
                  f"{before['sar']}/{before['dar']})", flush=True)
        secs, err = encode(path, tmp, a.qp, a.drop_audio, vf, a.set_dar)
        rec = {"src": path, "dst": dst, "qp": a.qp, "preset": "p6", "vf": vf,
               "set_dar": a.set_dar, "seconds": round(secs, 1),
               "before": before, "adopted": False}
        if not os.path.exists(tmp):
            rec["why"] = f"encode failed: {err[:150]}"
            print(f"      FAILED  {err[:120]}", flush=True)
        else:
            after = probe(tmp)
            ok = (after["codec"] == "hevc"
                  and abs(after["dur"] - before["dur"]) < max(2.0, before["dur"] * 0.02)
                  and (after["w"], after["h"]) == exp_wh
                  and after["sar"] == exp_sar and as_dar(after["dar"]) == exp_dar
                  and after["n_s"] == before["n_s"])
            audio_ok = after["n_a"] == (1 if a.drop_audio == "LAST" and before["n_a"] > 1
                                        else before["n_a"])
            clean, derr = decodes_clean(tmp)
            s, p = (None, None) if a.no_ssim else metrics(path, tmp, src_vf=vf or "",
                                                           from_start=a.metrics_from_start)
            new = os.path.getsize(tmp)
            gain = 1 - new / old
            rec.update(after=after, old_bytes=old, new_bytes=new, gain=round(gain, 4),
                       ssim=s, psnr=p, decodes_clean=clean, verified=ok and audio_ok)
            print(f"      -> {new/2**30:.2f} GB  ({gain:+.0%})  SSIM {s if s is None else round(s,4)}"
                  f"{'' if p is None else f'  PSNR {p:.1f} dB'}  {secs/60:.1f} min"
                  f"  {'ok' if ok and audio_ok else 'MISMATCH'}"
                  f"{'  DECODE-BAD' if not clean else ''}", flush=True)
            if not ok or not audio_ok:
                rec["why"] = "stream/aspect/duration mismatch against source"
                os.unlink(tmp)
                print(f"      REJECTED {before['w']}x{before['h']} SAR {before['sar']} "
                      f"{before['n_a']}a/{before['n_s']}s  vs  {after['w']}x{after['h']} "
                      f"SAR {after['sar']} DAR {after['dar']} {after['n_a']}a/{after['n_s']}s "
                      f"(expected {exp_wh[0]}x{exp_wh[1]} SAR {exp_sar} DAR {exp_dar})", flush=True)
            elif not clean:
                rec["why"] = f"encode does not decode clean: {derr}"
                os.unlink(tmp)
                print(f"      REJECTED decode errors: {derr[:100]}", flush=True)
            elif s is not None and s < a.min_ssim:
                rec["why"] = f"SSIM {s:.4f} below the {a.min_ssim} bar"
                os.unlink(tmp)
                print(f"      REJECTED quality: SSIM {s:.4f} < {a.min_ssim}", flush=True)
            elif not a.no_ssim and s is None:
                # an unmeasured encode is not a passing encode: ffmpeg exits 0 on a
                # comparison that processed zero frames, so silence is failure here
                rec["why"] = "SSIM could not be measured against the source"
                os.unlink(tmp)
                print("      REJECTED: no SSIM measured (comparison ran on nothing?)", flush=True)
            elif gain < a.min_gain:
                rec["why"] = f"only {gain:.0%} smaller, below the {a.min_gain:.0%} bar"
                os.unlink(tmp)
                print(f"      KEPT SOURCE  {old/2**30:.2f} -> {new/2**30:.2f} GB "
                      f"({gain:.0%}) is not worth a generation", flush=True)
            else:
                if a.out:
                    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
                    shutil.move(tmp, a.out)      # --out may be on another filesystem
                else:
                    os.replace(tmp, path)
                rec["adopted"] = True
                print(f"      ADOPTED    {old/2**30:.2f} -> {new/2**30:.2f} GB, "
                      f"saves {(old-new)/2**30:.2f} GB  -> {os.path.basename(dst)}", flush=True)
        with open(a.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    recs = [json.loads(l) for l in open(a.log, encoding="utf-8")]
    ad = [r for r in recs if r.get("adopted")]
    if ad:
        print(f"\n   adopted {len(ad)} of {len(recs)} attempted")
        print(f"   {sum(r['old_bytes'] for r in ad)/2**30:.1f} GB -> "
              f"{sum(r['new_bytes'] for r in ad)/2**30:.1f} GB, saved "
              f"{(sum(r['old_bytes'] for r in ad)-sum(r['new_bytes'] for r in ad))/2**30:.1f} GB")
        ss = [r["ssim"] for r in ad if r.get("ssim")]
        if ss:
            print(f"   SSIM against source: min {min(ss):.4f}, mean {sum(ss)/len(ss):.4f}")


if __name__ == "__main__":
    main()
