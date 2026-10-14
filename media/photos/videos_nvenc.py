#!/usr/bin/env python3
"""Video pass: move the 364 remaining clips out of the photo library into

/mnt/xfs/videos/videos, re-encoding to HEVC with the RTX 5080.

Rules learned the hard way earlier in this job:
  - a source is unlinked only after the output is probed (duration within 1%),
    fully decoded, and confirmed smaller; otherwise the source stream is
    copied across unchanged and that is recorded in the manifest
  - already-lean HEVC stays untouched (stream copy), wasteful HEVC is re-done
  - AAC audio is copied, PCM/LPCM from MOVs is turned into AAC so the file
    plays everywhere
  - two workers maximum: the card is shared with chat and the movie job
Usage: python3 videos_nvenc.py [--limit N] [--only-copy]
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/videos_nvenc.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

FFMPEG = '/usr/bin/ffmpeg'
FFPROBE = '/usr/bin/ffprobe'
from paths import LIB as OLD
from paths import VIDLIB as VDIR
WORK = '/home/lario/photos-reorg-work'
MANIFEST = f'{WORK}/manifest-videos.csv'
LOG = f'{WORK}/videos.log'
CQ = 23
LEAN_BPP = 0.20            # bits/pixel below which an existing HEVC is left alone
LOCK = threading.Lock()

_lease = None


def log(msg):
    line = f'{dt.datetime.now():%H:%M:%S} {msg}'
    with LOCK:
        print(line, flush=True)
        with open(LOG, 'a') as fh:
            fh.write(line + '\n')


def probe(path):
    r = subprocess.run(
        [FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=codec_name,width,height,pix_fmt,r_frame_rate:format='
         'duration,size,bit_rate', '-show_entries', 'stream=codec_type:stream=codec_name',
         '-of', 'json', path], capture_output=True, text=True)
    d = json.loads(r.stdout or '{}')
    st = next((s for s in d.get('streams', []) if s.get('codec_type') == 'video'), {})
    fmt = d.get('format', {})
    aud = [s.get('codec_name') for s in d.get('streams', [])
           if s.get('codec_type') == 'audio']
    dur = float(fmt.get('duration') or 0)
    size = int(fmt.get('size') or os.path.getsize(path))
    w = int(st.get('width') or 0)
    h = int(st.get('height') or 0)
    bpp = (size * 8) / (dur * w * h) if dur and w and h else 9.9
    return {'codec': st.get('codec_name'), 'w': w, 'h': h,
            'pix': st.get('pix_fmt') or '', 'fps': st.get('r_frame_rate') or '',
            'dur': dur, 'size': size, 'audio': aud, 'bpp': bpp,
            'tenbit': '10le' in (st.get('pix_fmt') or '')}


def decode_clean(path):
    p = subprocess.run([FFMPEG, '-v', 'error', '-i', path, '-f', 'null', '-'],
                       capture_output=True, text=True)
    err = p.stderr.strip()
    return p.returncode == 0 and not err, err[:300]


def encode(src, tmp, info, stamp):
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', '-i', src,
           '-map', '0:v:0', '-map', '0:a?', '-map', '0:s?',
           '-c:v', 'hevc_nvenc', '-preset', 'p5', '-tune', 'hq',
           '-rc', 'vbr', '-cq', str(CQ), '-b:v', '0',
           '-tag:v', 'hvc1', '-pix_fmt', 'p010le' if info['tenbit'] else 'yuv420p']
    cmd += ['-c:a', 'aac', '-b:a', '192k'] if any(
        a not in ('aac', 'mp3') for a in info['audio']) else ['-c:a', 'copy']
    cmd += ['-c:s', 'copy', '-map_metadata', '0', '-movflags', '+faststart']
    if stamp:
        cmd += ['-metadata', f'creation_time={stamp}']
    cmd += [tmp]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, p.stderr.strip()[:300]


def creation_stamp(e):
    d = e.get('dt')
    return f'{d.replace(" ", "T")}Z' if d else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only-copy', action='store_true')
    ap.add_argument('--workers', type=int, default=2)
    a = ap.parse_args()

    vm = json.load(open(f'{WORK}/videomap.json'))
    done = set()
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as fh:
            done = {r['orig'] for r in csv.DictReader(fh)}
    items = sorted(rel for rel in vm if rel not in done)
    if a.only_copy:
        items = [r for r in items if probe(os.path.join(OLD, r))['codec'] == 'hevc'
                 and probe(os.path.join(OLD, r))['bpp'] < LEAN_BPP]
    if a.limit:
        items = items[:a.limit]
    log(f'start: {len(items)} videos, cq={CQ}, workers={a.workers}')

    cols = ['orig', 'dest', 'dest_dir', 'dest_name', 'dt', 'vcodec', 'w', 'h',
            'fps', 'dur_s', 'bpp', 'in_bytes', 'out_bytes', 'ratio', 'mode', 'note']
    new = not os.path.exists(MANIFEST)
    mf = open(MANIFEST, 'a', newline='')
    mw = csv.DictWriter(mf, fieldnames=cols)
    if new:
        mw.writeheader()
    tally = {'nvenc': [0, 0, 0], 'copy-hevc': [0, 0, 0], 'no-gain-copy': [0, 0, 0],
             'fallback-copy': [0, 0, 0], 'ERROR': [0, 0, 0]}

    def work(rel):
        row = {c: '' for c in cols}
        src = os.path.join(OLD, rel)
        e = vm[rel]
        row.update(orig=rel, dest=e['dest'], dest_dir=e['dest_dir'],
                   dest_name=e['dest_name'], dt=e['dt'] or '')
        dst = os.path.join(VDIR, e['dest'])
        # keep the real container extension on the temp file so ffmpeg can pick
        # the muxer; a trailing .enc would leave it guessing
        tmp = f'{dst}.enc{os.path.splitext(dst)[1]}'
        if not os.path.exists(src):
            row.update(mode='ERROR', note='source missing')
            tally['ERROR'][0] += 1
            return row
        try:
            info = probe(src)
            row.update(vcodec=info['codec'], w=info['w'], h=info['h'],
                       fps=info['fps'], dur_s=round(info['dur'], 2),
                       bpp=round(info['bpp'], 3), in_bytes=info['size'])
            lean_hevc = info['codec'] == 'hevc' and info['bpp'] < LEAN_BPP
            mode = 'copy-hevc' if lean_hevc else 'nvenc'
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if lean_hevc:
                shutil.copy2(src, tmp)
            else:
                ok, err = encode(src, tmp, info, creation_stamp(e))
                if not ok:
                    log(f'  ffmpeg failed {rel}: {err[:160]}')
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                    shutil.copy2(src, tmp)
                    mode = 'fallback-copy'
            out = probe(tmp)
            ok = out['dur'] >= info['dur'] * 0.99 and out['size'] < info['size']
            if ok and mode == 'nvenc':
                ok, detail = decode_clean(tmp)
                if not ok:
                    log(f'  decode failed {rel}: {detail[:140]}')
                    mode = 'fallback-copy'
            if not ok and mode == 'nvenc':
                why = 'no size gain' if out['size'] >= info['size'] else 'bad output'
                log(f'  {why}: {rel} '
                    f'{info["size"]/2**20:.1f} -> {out["size"]/2**20:.1f} MB')
                if os.path.exists(tmp):
                    os.unlink(tmp)
                shutil.copy2(src, tmp)
                mode = ('no-gain-copy' if out['size'] >= info['size']
                        else 'fallback-copy')
                out = probe(tmp)
            sz = os.path.getsize(tmp)
            if sz != out['size']:
                raise RuntimeError(f'size mismatch {sz} vs {out["size"]}')
            if out['size'] > info['size']:
                raise RuntimeError(f'output larger than source ({mode})')
            os.replace(tmp, dst)
            os.unlink(src)
            row.update(out_bytes=sz, mode=mode,
                       ratio=round(sz / info['size'], 3))
            t = tally[mode]
            t[0] += 1
            t[1] += info['size']
            t[2] += sz
            log(f'  {mode:14} {info["size"]/2**20:8.1f} -> {sz/2**20:7.1f} MB '
                f'{info["codec"]}->{os.path.splitext(dst)[1]} '
                f'{e["dest"][:60]}')
        except Exception as ex:
            if os.path.exists(tmp):
                os.unlink(tmp)
            row.update(mode='ERROR', note=f'{type(ex).__name__}: {ex}')
            tally['ERROR'][0] += 1
            log(f'  ERROR {rel}: {type(ex).__name__}: {ex}')
        return row

    with ThreadPoolExecutor(a.workers) as ex:
        for row in ex.map(work, items):
            with LOCK:
                mw.writerow(row)
                mf.flush()
    mf.close()
    log('done: ' + '  '.join(f'{k}={v[0]} '
                             f'({v[1]/2**30:.2f}->{v[2]/2**30:.2f} GB)'
                             for k, v in tally.items() if v[0]))


if __name__ == "__main__":
    main()
