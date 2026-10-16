#!/usr/bin/env python3
"""Safety verification of the video pass.


manifest-videos.csv stores dest relative to the video root. For each row:
  byte-identical copy  -> blake2b equality, no media checks needed
  otherwise            -> stream summary with rotation awareness (a -90 display
                          matrix baked into pixels is fine; a lost or doubled
                          rotation is not), packet-count parity with the source
                          (catches truncation and frame loss where duration
                          headers are broken, e.g. the mjpeg .AVIs), audio kept,
                          and a full strict decode of the output.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/verify_videos.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import hashlib
import json
import os
import subprocess

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import BACKUP as BK
from paths import VIDLIB as ROOT
FFPROBE = '/usr/bin/ffprobe'
FFMPEG = '/usr/bin/ffmpeg'


def run(c, t=1800):
    return subprocess.run(c, capture_output=True, text=True, timeout=t)


def digest(p, chunk=1 << 22):
    h = hashlib.blake2b()
    with open(p, 'rb') as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


ENTRIES = ('format=duration:stream=codec_type,codec_name,width,height,'
           'stream_disposition:stream_side_data=rotation,side_data_type')


def summary(p):
    r = run([FFPROBE, '-v', 'error', '-show_entries', ENTRIES, '-of', 'json', p], 300)
    pk = run([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-count_packets',
              '-show_entries', 'stream=nb_read_packets', '-of', 'json', p], 1200)
    try:
        d = json.loads(r.stdout or '{}')
        pks = json.loads(pk.stdout or '{}').get('streams', [])
    except Exception:
        return None
    v = next((s for s in d.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not v:
        return None
    rot = 0
    for sd in v.get('side_data_list', []) or []:
        if sd.get('side_data_type') == 'Display Matrix':
            rot = int(round(float(sd.get('rotation') or 0)))
    try:
        dur = float(d.get('format', {}).get('duration') or 0)
    except (TypeError, ValueError):
        dur = 0.0
    return dict(dur=dur, vcodec=v.get('codec_name'), w=v.get('width'), h=v.get('height'),
                rot=rot, packets=int(pks[0].get('nb_read_packets') or 0) if pks else 0,
                n_audio=sum(1 for s in d.get('streams', []) if s.get('codec_type') == 'audio'),
                size=os.path.getsize(p))


def decode_ok(p):
    r = run([FFMPEG, '-v', 'error', '-xerror', '-nostdin', '-i', p,
             '-map', '0:v:0', '-f', 'null', '-'], 1800)
    return r.returncode == 0, (r.stderr or '').strip()[-200:]


def compare(a, b):
    why = []
    if a['dur'] > 0.5 and b['dur'] and b['dur'] < a['dur'] * 0.99:
        why.append(f"duration {a['dur']:.1f}->{b['dur']:.1f}")
    if a['packets'] and b['packets'] < a['packets'] * 0.995:
        why.append(f"packets {a['packets']}->{b['packets']}")
    if a['w'] and b['w']:
        same = (a['w'], a['h']) == (b['w'], b['h'])
        swap = (a['w'], a['h']) == (b['h'], b['w'])
        applied = a['rot'] and not b['rot'] and swap          # matrix baked into pixels: fine
        bad_rot = (a['rot'] and b['rot'] and swap) or (a['rot'] and not b['rot'] and not same and not swap)
        if not same and not applied:
            why.append(f"dims {a['w']}x{a['h']}@{a['rot']}->{b['w']}x{b['h']}@{b['rot']}"
                       + (' DOUBLE-ROTATION' if bad_rot else ''))
    if a['n_audio'] and not b['n_audio']:
        why.append('audio-lost')
    if b['size'] < max(2048, a['size'] * 0.01):
        why.append(f"suspiciously-small {a['size']}->{b['size']}")
    if a['vcodec'] == 'hevc' and b['vcodec'] not in ('hevc', 'h264'):
        why.append(f"codec {a['vcodec']}->{b['vcodec']}")
    return why


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-videos.csv'))))
    only = [a for a in __import__('sys').argv[1:] if not a.startswith('-')]
    if only:
        rows = [r for r in rows if any(o.lower() in r['orig'].lower() for o in only)]
        print(f'filtered to {len(rows)} row(s)')
    bad, verbatim, media = [], 0, 0
    for i, row in enumerate(rows, 1):
        src = os.path.join(BK, row['orig'])
        dst = os.path.join(ROOT, row['dest'])
        why = []
        if not os.path.isfile(src):
            why.append('backup-missing')
        if not os.path.isfile(dst):
            why.append('DEST-MISSING')
        elif os.path.getsize(src) == os.path.getsize(dst) and digest(src) == digest(dst):
            verbatim += 1
        else:
            a = summary(src) if os.path.isfile(src) else None
            b = summary(dst)
            if a is None:
                why.append('original-unreadable')
            if b is None:
                why.append('OUTPUT-UNREADABLE')
            if a and b:
                why += compare(a, b)
            media += 1
        if why:
            ok, err = (False, 'no file')
            if os.path.isfile(dst):
                ok, err = decode_ok(dst)
            if not ok:
                why.append('DECODE-FAIL ' + err)
            bad.append({'orig': row['orig'], 'dest': dst, 'mode': row['mode'], 'why': why})
            print(f"PROBLEM {row['orig']}: {why}", flush=True)
        if i % 20 == 0:
            print(f"  {i}/{len(rows)} verbatim {verbatim} media {media} problems {len(bad)}", flush=True)
    out = os.path.join(W, 'verify-videos-problems-subset.json' if only
                       else 'verify-videos-problems.json')
    json.dump(bad, open(out, 'w'), indent=1, default=str)
    print(f"\nDONE {len(rows)} rows: byte-identical {verbatim}, media-checked {media}, problems {len(bad)}")
    print('modes:', {m: sum(1 for r in rows if r['mode'] == m) for m in set(r['mode'] for r in rows)})
    before = sum(int(r['in_bytes']) for r in rows)
    after = sum(int(r['out_bytes']) for r in rows)
    print(f"volume: {before/1e9:.2f} GB -> {after/1e9:.2f} GB")


if __name__ == "__main__":
    main()
