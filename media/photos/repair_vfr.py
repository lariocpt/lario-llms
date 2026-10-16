#!/usr/bin/env python3
"""Repair the two variable-frame-rate clips whose NVENC pass dropped frames.


The first pass (and a -fps_mode vfr retry) encoded these at the stream's nominal
CFR rate and lost ~12% of the frames; -fps_mode passthrough keeps every frame and
the exact duration. Verifies decoded frame count, duration, strict decode and
size before replacing the output, then rewrites the manifest row.
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/repair_vfr.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import csv
import json
import os
import subprocess
import time

from paths import W        # evidence root: config.PHOTO_WORK, env W
os.makedirs(W, exist_ok=True)      # one evidence root for the whole pass
from paths import BACKUP as BK
from paths import VIDLIB as ROOT
FF = '/usr/bin/ffmpeg'
FP = '/usr/bin/ffprobe'

TARGETS = ['March 27, 2017/Photos - 3433 of 6286.mp4',
           'b041a19f-4047-47f8-928c-5f1efce5de1b.mp4']


def run(c, t=900):
    return subprocess.run(c, capture_output=True, text=True, timeout=t)


def json_probe(p, entries, *extra):
    r = run([FP, '-v', 'error'] + list(extra) + ['-show_entries', entries, '-of', 'json', p])
    try:
        return json.loads(r.stdout or '{}')
    except Exception:
        return {}


def frames(p):
    s = (json_probe(p, 'stream=nb_read_frames', '-select_streams', 'v:0', '-count_frames')
         .get('streams') or [{}])[0]
    try:
        return int(s.get('nb_read_frames') or 0)
    except (TypeError, ValueError):
        return 0


def dur(p):
    try:
        return float((json_probe(p, 'format=duration').get('format') or {})['duration'])
    except (KeyError, TypeError, ValueError):
        return 0.0


def created(p):
    r = run([FP, '-v', 'error', '-show_entries', 'format_tags=creation_time',
             '-of', 'default=nw=1:nk=1', p])
    v = (r.stdout or '').strip()
    return v if v and not v.startswith('[N/A]') else ''


def main():
    rows = list(csv.DictReader(open(os.path.join(W, 'manifest-videos.csv'))))
    by_orig = {r['orig']: r for r in rows}
    log = []
    for orig in TARGETS:
        row = by_orig[orig]
        src = os.path.join(BK, orig)
        dst = os.path.join(ROOT, row['dest'])
        tmp = dst + '.passthrough.mp4'
        f_src, d_src, ct = frames(src), dur(src), created(src)
        cmd = [FF, '-hide_banner', '-nostdin', '-y', '-i', src,
               '-map', '0:v:0', '-map', '0:a?', '-map', '0:s?', '-fps_mode', 'passthrough',
               '-c:v', 'hevc_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '23',
               '-b:v', '0', '-tag:v', 'hvc1', '-pix_fmt', 'yuv420p',
               '-c:a', 'copy', '-c:s', 'copy', '-movflags', '+faststart', '-map_metadata', '0']
        if ct:
            cmd += ['-metadata', f'creation_time={ct}']
        cmd += [tmp]
        r = run(cmd, 900)
        f_new, d_new, s_new = frames(tmp), dur(tmp), os.path.getsize(tmp)
        why = []
        if r.returncode != 0:
            why.append(f'ffmpeg rc={r.returncode} {(r.stderr or "")[-160:]}')
        if f_src and f_new < f_src:
            why.append(f'frames still short {f_src}->{f_new}')
        if d_src and abs(d_new - d_src) > max(0.05, d_src * 0.01):
            why.append(f'duration moved {d_src}->{d_new}')
        if s_new >= int(row['in_bytes']):
            why.append(f'not smaller than source {s_new}')
        if not why:
            d = run([FF, '-v', 'error', '-xerror', '-nostdin', '-i', tmp, '-map', '0:v:0',
                     '-f', 'null', '-'], 900)
            if d.returncode != 0:
                why.append('decode failed ' + (d.stderr or '')[-160:])
        if why:
            print(f'REJECT {orig}: {why}')
            if os.path.exists(tmp):
                os.remove(tmp)
            log.append({'orig': orig, 'result': 'rejected', 'why': why})
            continue
        os.replace(tmp, dst)
        old = dst + '.before-vfr-repair'
        in_b = int(row['in_bytes'])
        new = os.path.getsize(dst)
        row['out_bytes'] = str(new)
        row['ratio'] = f'{new / in_b:.3f}'
        row['mode'] = 'nvenc'
        row['note'] = (f'vfr-repair (fps_mode passthrough) {time.strftime("%Y-%m-%dT%H:%M")},'
                       f' frames {f_src} kept; superseded outputs removed')
        if os.path.exists(old):
            os.remove(old)
        log.append({'orig': orig, 'result': 'repaired', 'frames': f_src, 'duration': d_new,
                    'in_bytes': in_b, 'out_bytes': new, 'ratio': new / in_b})
        print(f'REPAIRED {orig}: frames {f_src} kept, dur {d_new:.2f}s,'
              f' {in_b/1e6:.1f} -> {new/1e6:.1f} MB ({new/in_b:.3f})')
    with open(os.path.join(W, 'manifest-videos.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    json.dump(log, open(os.path.join(W, 'repair-vfr.json'), 'w'), indent=1)
    print('repairs:', len([l for l in log if l['result'] == 'repaired']), 'of', len(TARGETS))


if __name__ == "__main__":
    main()
