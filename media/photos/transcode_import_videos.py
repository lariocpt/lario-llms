#!/usr/bin/env python3
"""Transcode the 66 video files imported from the hhd source trees into the
video library, with the same rules videos_nvenc.py used for the original pass:

  - HEVC on the RTX 5080, hevc_nvenc -preset p5 -tune hq -rc vbr -cq 23 -b:v 0
  - a source is dropped only after the output is probed (duration within 1 %),
    strictly decoded, and confirmed smaller; otherwise the source is copied
    across unchanged and recorded as such
  - already-lean HEVC (bpp < 0.20) is stream-copied, AAC/MP3 audio is copied,
    everything else becomes AAC 192k so it plays everywhere
  - two workers: the card is shared with chat

Added for this import, both recorded per file in manifest-videos.csv:
  - interlaced sources (PAL DV, DVD VOB, MPEG-1 captures) are deinterlaced with
    yadif; encoding 25i as-is combs badly on a phone
  - variable-frame-rate sources get -fps_mode passthrough and their decoded
    frame count is checked against the source, which is what repair_vfr.py
    learned for the two clips the first pass shortened
  - the two DVD VIDEO_TS sets become one MP4 per disc: the main title's
    VTS_01_n.VOB chain is byte-concatenated, menus/IFO/BUP are not imported

Usage: python3 transcode_import_videos.py [--limit N] [--dry]
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

FFMPEG = '/usr/bin/ffmpeg'
FFPROBE = '/usr/bin/ffprobe'
W = '/home/lario/photos-reorg-work'
from paths import HHD
ROOTS = {'Mac Photos': f'{HHD}/Mac Photos', 'Photosusa': f'{HHD}/Photosusa'}
from paths import VIDLIB as VDIR
MANIFEST = f'{W}/manifest-videos.csv'
LOG = f'{W}/transcode-import-videos.log'
CQ = 23
LEAN_BPP = 0.20
LOCK = threading.Lock()

# DVD sets: the main title of each disc, in play order, and where it lands
DVD_MENUS_DROPPED = []


def log(msg):
    line = f'{dt.datetime.now():%H:%M:%S} {msg}'
    with LOCK:
        print(line, flush=True)
        with open(LOG, 'a') as fh:
            fh.write(line + '\n')


def run(cmd, t=3600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=t)


def spec(job):
    """ffmpeg input arguments for a job: a plain file, or the concat demuxer
    reading a disc's main-title VOB chain in play order."""
    if job['kind'] != 'dvd':
        return ['-i', job['inputs'][0]]
    lst = f'/tmp/opencode/dvd-{abs(hash(tuple(job["inputs"])))}.txt'
    with open(lst, 'w') as fh:
        for s in job['inputs']:
            fh.write("file '%s'\n" % s.replace("'", "'\\''"))
    return ['-f', 'concat', '-safe', '0', '-i', lst]


def probe(*input_args, size_hint=0):
    # no -select_streams here: the audio list below is what decides whether the
    # output can copy its audio, and selecting v:0 hid every audio stream from
    # the JSON - that made the first run of this script use -c:a copy for
    # everything, which cannot mux PCM into MP4 (see fix_video_audio.py)
    r = run([FFPROBE, '-v', 'error', '-show_entries',
             'stream=codec_name,codec_type,width,height,pix_fmt,r_frame_rate,'
             'avg_frame_rate,field_order,nb_frames:format=duration,size,bit_rate',
             '-of', 'json', *input_args])
    d = json.loads(r.stdout or '{}')
    st = next((s for s in d.get('streams', []) if s.get('codec_type') == 'video'), {})
    fmt = d.get('format', {})
    aud = [s.get('codec_name') for s in d.get('streams', [])
           if s.get('codec_type') == 'audio']
    dur = float(fmt.get('duration') or 0)
    size = int(fmt.get('size') or 0) or size_hint
    w, h = int(st.get('width') or 0), int(st.get('height') or 0)
    rfr, afr = st.get('r_frame_rate') or '', st.get('avg_frame_rate') or ''

    def frac(s):
        try:
            a, b = s.split('/')
            return float(a) / float(b)
        except Exception:
            return 0.0
    rf, af = frac(rfr), frac(afr)
    inter = (st.get('field_order') in ('tt', 'bb', 'tb', 'bt')
             or any(str(a).lower().endswith('.dv') for a in input_args))
    return {'codec': st.get('codec_name'), 'w': w, 'h': h, 'pix': st.get('pix_fmt') or '',
            'fps': rfr, 'avg_fps': afr, 'dur': dur, 'size': size, 'audio': aud,
            'bpp': (size * 8) / (dur * w * h) if dur and w and h else 9.9,
            'tenbit': '10le' in (st.get('pix_fmt') or ''),
            'interlaced': inter, 'vfr': bool(rf and af and abs(rf - af) / rf > 0.02),
            'nb_frames': int(st.get('nb_frames') or 0)}


def frames(*input_args):
    r = run([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-count_frames',
             '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', *input_args], 1800)
    try:
        return int((r.stdout or '').strip().split('\n')[0])
    except (ValueError, IndexError):
        return 0


def decode_clean(path):
    p = run([FFMPEG, '-v', 'error', '-xerror', '-i', path, '-f', 'null', '-'])
    err = p.stderr.strip()
    cnt = re.search(r'frame=\s*(\d+)', (p.stderr or '').split('\r')[-1]
                    if p.stderr else '')
    return p.returncode == 0 and not err, err[:300], (int(cnt.group(1)) if cnt else 0)


# The Elephant Sanctuary disc carries no usable timestamp at all - its only
# date is 2006-12-31 17:00:00, a DVD-authoring default. It belongs to the
# Dec 2010 Garden Route trip, so it goes next to that trip's other date-less
# clips instead of pretending to be from 2006.
UNDATED_OVERRIDE = {'Elephant Sanctuary Tour DVD': 'Undated/Garden Route Trip'}


def orig_of(e):
    """Identity used in the manifest and in the already-done check: the source
    path for a loose file, the archive and entry path for an archive entry."""
    return e.get('prov') or f"{e['src_tree']}/{e['rel']}"


def build_jobs():
    """One job per output file. The DVD sets collapse to their main title."""
    plan = json.load(open(f"{W}/{os.environ.get('PLAN', 'import-plan.json')}"))
    vids = {ap: e for ap, e in plan.items() if e['isvid']}
    jobs, vobs = [], defaultdict(list)
    for ap, e in vids.items():
        if e['ext'] == '.vob':
            vobs[os.path.dirname(os.path.dirname(ap))].append(
                (os.path.basename(ap).upper(), ap, e))
            continue
        jobs.append({'inputs': [ap], 'proto': e, 'kind': 'file'})
    for disc, items in vobs.items():
        title = sorted(items)
        keep = [x for x in title if x[0].startswith('VTS_01_')]
        for _n, path, e in title:
            if not _n.startswith('VTS_01_'):
                DVD_MENUS_DROPPED.append({'file': path, 'bytes': e['bytes'],
                                          'disc': os.path.basename(disc)})
        base = keep[0][2]
        jobs.append({'inputs': [x[1] for x in keep], 'proto': base, 'kind': 'dvd',
                     'disc': os.path.basename(disc)})
    # number the outputs per destination folder, by capture time, continuing
    # whatever is already in that folder of the video library
    bydir = defaultdict(list)
    for j in jobs:
        if j['kind'] == 'dvd' and j['disc'] in UNDATED_OVERRIDE:
            j['proto'] = dict(j['proto'], dt=None,
                              dir=f'{VDIR}/{UNDATED_OVERRIDE[j["disc"]]}')
        bydir[j['proto']['dir']].append(j)
    for d, js in bydir.items():
        js.sort(key=lambda j: (j['proto']['dt'] or '0000', os.path.basename(j['inputs'][0])))
        existing = 0
        if os.path.isdir(d):
            existing = max([int(m.group(1)) for f in os.listdir(d)
                            if (m := re.match(r'(\d{3})_', f))] or [0])
        for i, j in enumerate(js, 1):
            j['dest'] = os.path.join(d, f'{existing + i:03d}_{stem(j)}.mp4')
    return jobs


def stem(job):
    """NNN_ part of the file name: the capture time, or what the thing actually
    is when there is no timestamp (the library's undated convention)."""
    e = job['proto']
    if e['dt']:
        return e['dt'][:10].replace('-', '') + '-' + e['dt'][11:].replace(':', '')
    if job['kind'] == 'dvd':
        return re.sub(r'\s*(Tour\s*)?DVD$', '', job['disc'], flags=re.I).strip() or 'DVD'
    return re.sub(r'[^\w.-]+', '_',
                  os.path.splitext(os.path.basename(job['inputs'][0]))[0])[:40]


def encode(job, tmp, info, t=0):
    e = job['proto']
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', *spec(job)]
    if t:
        cmd += ['-t', str(t)]
    cmd += ['-map', '0:v:0', '-map', '0:a?', '-map', '0:s?']
    if info['vfr']:
        cmd += ['-fps_mode', 'passthrough']
    if info['interlaced']:
        cmd += ['-vf', 'yadif=0:-1:0']
    cmd += ['-c:v', 'hevc_nvenc', '-preset', 'p5', '-tune', 'hq',
            '-rc', 'vbr', '-cq', str(CQ), '-b:v', '0', '-tag:v', 'hvc1',
            '-pix_fmt', 'p010le' if info['tenbit'] else 'yuv420p']
    cmd += (['-c:a', 'aac', '-b:a', '192k']
            if any(a not in ('aac', 'mp3') for a in info['audio']) else ['-c:a', 'copy'])
    cmd += ['-c:s', 'copy', '-map_metadata', '0', '-movflags', '+faststart']
    if e.get('dt'):
        cmd += ['-metadata', f'creation_time={e["dt"].replace(" ", "T")}Z']
    cmd += [tmp]
    p = run(cmd)
    return p.returncode == 0, (p.stderr or '').strip()[-300:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--test', type=float, default=0,
                    help='encode only N seconds of each job and keep nothing')
    ap.add_argument('--workers', type=int, default=2)
    a = ap.parse_args()

    jobs = build_jobs()
    done = set()
    if os.path.exists(MANIFEST):
        done = {r['orig'] for r in csv.DictReader(open(MANIFEST))}
    jobs = [j for j in jobs if orig_of(j['proto']) not in done]
    if a.limit:
        jobs = jobs[:a.limit]
    if a.test:
        picks = []
        for want in ('.vob', '.dv', '.mpg', '.mov', '.avi'):
            picks += [j for j in jobs if j['proto']['ext'] == want][:1]
        for j in picks:
            ias = spec(j)
            in_bytes = sum(os.path.getsize(s) for s in j['inputs'])
            info = probe(*ias, size_hint=in_bytes)
            if j['kind'] == 'dvd':
                info['dur'] = sum(probe('-i', s)['dur'] for s in j['inputs'])
            tmp = '/tmp/opencode/testenc.mp4'
            if os.path.exists(tmp):
                os.unlink(tmp)
            ok, err = encode(j, tmp, info, t=a.test)
            got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            out = probe('-i', tmp) if ok and got else {}
            bits = ''
            if out:
                bits = ('%dx%d %s %.1fs inter=%d' % (out['w'], out['h'], out['codec'],
                                                     out['dur'], int(out['interlaced'])))
            log('  TEST %-5s src %6.1f MB %-10s -> %7.2f MB / %.0fs  %s %s'
                % (j['proto']['ext'], in_bytes / 2**20, info['codec'], got / 2**20,
                   a.test, bits, err[:110]))
            if os.path.exists(tmp):
                os.unlink(tmp)
        return
    log(f'start: {len(jobs)} outputs from {sum(len(j["inputs"]) for j in jobs)} source files, '
        f'cq={CQ}, workers={a.workers}; DVD menus not imported: {len(DVD_MENUS_DROPPED)}')
    if a.dry:
        for j in jobs:
            info = probe(*spec(j), size_hint=sum(os.path.getsize(s) for s in j['inputs']))
            if j['kind'] == 'dvd':
                info['dur'] = sum(probe('-i', s)['dur'] for s in j['inputs'])
            log(f'  {j["kind"]:3} {info["codec"]:11} {info["size"]/2**20:8.1f} MB '
                f'{info["dur"]:7.0f}s {info["w"]}x{info["h"]} '
                f'inter={int(info["interlaced"])} vfr={int(info["vfr"])} '
                f'{os.path.relpath(j["dest"], VDIR)}')
        for m in DVD_MENUS_DROPPED:
            log(f'  drop {m["disc"]:36} {m["bytes"]/2**20:8.1f} MB menu '
                f'{os.path.basename(m["file"])}')
        return

    cols = ['orig', 'dest', 'dest_dir', 'dest_name', 'dt', 'vcodec', 'w', 'h', 'fps',
            'dur_s', 'bpp', 'in_bytes', 'out_bytes', 'ratio', 'mode', 'note']
    fresh = not os.path.exists(MANIFEST)
    mf = open(MANIFEST, 'a', newline='')
    mw = csv.DictWriter(mf, fieldnames=cols)
    if fresh:
        mw.writeheader()
    tally = defaultdict(lambda: [0, 0, 0])

    def work(job):
        e = job['proto']
        row = {c: '' for c in cols}
        orig_tag = orig_of(e)
        rel_dest = os.path.relpath(job['dest'], VDIR)
        row.update(orig=orig_tag, dest=rel_dest, dest_dir=os.path.dirname(rel_dest),
                   dest_name=os.path.basename(rel_dest), dt=e['dt'] or '')
        dst = job['dest']
        srcs = job['inputs']
        ias = spec(job)
        tmp = f'{dst}.enc.mp4'
        in_bytes = sum(os.path.getsize(s) for s in srcs)
        row['in_bytes'] = in_bytes
        note = []
        if job['kind'] == 'dvd':
            note.append('DVD main title VTS_01_* concatenated'
                        f' ({len(srcs)} VOB); menus/IFO/BUP not imported')
        try:
            info = probe(*ias, size_hint=in_bytes)
            if job['kind'] == 'dvd':
                # the concat demuxer reports no duration or size for MPEG-PS,
                # so measure the disc from its own parts
                info['dur'] = sum(probe('-i', s)['dur'] for s in srcs)
                info['size'] = in_bytes
            row.update(vcodec=info['codec'], w=info['w'], h=info['h'], fps=info['fps'],
                       dur_s=round(info['dur'], 2), bpp=round(info['bpp'], 3))
            lean = info['codec'] == 'hevc' and info['bpp'] < LEAN_BPP and job['kind'] != 'dvd'
            mode = 'copy-hevc' if lean else 'nvenc'
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            want_frames = frames(*ias) if info['vfr'] else 0
            if info['interlaced']:
                note.append('yadif deinterlace')
            if info['vfr']:
                note.append(f'vfr passthrough ({info["fps"]} nominal, '
                            f'{info["avg_fps"]} average), {want_frames} frames')
            if lean:
                shutil.copy2(srcs[0], tmp)
            else:
                ok, err = encode(job, tmp, info)
                if not ok:
                    log(f'  ffmpeg failed {orig_tag}: {err[:150]}')
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                    mode = 'fallback-copy'
            if mode != 'fallback-copy':
                out = probe('-i', tmp)
                bad = []
                if out['dur'] < info['dur'] * 0.99:
                    bad.append(f'duration {info["dur"]:.1f} -> {out["dur"]:.1f}')
                if out['size'] >= in_bytes:
                    bad.append(f'no size gain {in_bytes / 2**20:.1f} -> {out["size"] / 2**20:.1f} MB')
                if want_frames:
                    got = frames(tmp)
                    if got < want_frames:
                        bad.append(f'frames {want_frames} -> {got}')
                if not bad:
                    clean, detail, _ = decode_clean(tmp)
                    if not clean:
                        bad.append('decode: ' + detail[:120])
                if bad:
                    mode = ('no-gain-copy' if any('size gain' in b for b in bad)
                            else 'fallback-copy')
                    log(f'  {mode} {orig_tag}: {"; ".join(bad)[:150]}')
                    note.append('not re-encoded: ' + '; '.join(bad)[:120])
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            if mode in ('copy-hevc', 'no-gain-copy', 'fallback-copy'):
                # keep the source container when the bytes are not being re-muxed
                if job['kind'] == 'dvd':
                    dst = re.sub(r'\.mp4$', '.vob', dst)
                    rel_dest = os.path.relpath(dst, VDIR)
                    row.update(dest=rel_dest, dest_name=os.path.basename(dst))
                    with open(tmp + '.cat', 'wb') as out_fh:
                        for s in srcs:
                            with open(s, 'rb') as in_fh:
                                shutil.copyfileobj(in_fh, out_fh, 1 << 22)
                    os.replace(tmp + '.cat', tmp)
                else:
                    dst = re.sub(r'\.mp4$', os.path.splitext(srcs[0])[1].lower(), dst)
                    rel_dest = os.path.relpath(dst, VDIR)
                    row.update(dest=rel_dest, dest_name=os.path.basename(dst))
                    shutil.copy2(srcs[0], tmp)
            sz = os.path.getsize(tmp)
            if sz > in_bytes:
                raise RuntimeError(f'output larger than source ({mode})')
            os.replace(tmp, dst)
            for s in srcs:
                os.unlink(s)
            row.update(out_bytes=sz, mode=mode, ratio=round(sz / in_bytes, 3),
                       note='; '.join(note))
            t = tally[mode]
            t[0] += 1
            t[1] += in_bytes
            t[2] += sz
            log(f'  {mode:14} {in_bytes / 2**20:8.1f} -> {sz / 2**20:7.1f} MB '
                f'{info["codec"]:11} {rel_dest[:64]}')
        except Exception as ex:
            if os.path.exists(tmp):
                os.unlink(tmp)
            row.update(mode='ERROR', note=f'{type(ex).__name__}: {ex}')
            tally['ERROR'][0] += 1
            log(f'  ERROR {orig_tag}: {type(ex).__name__}: {ex}')
        return row

    with ThreadPoolExecutor(a.workers) as ex:
        for row in ex.map(work, jobs):
            with LOCK:
                mw.writerow(row)
                mf.flush()
    mf.close()
    log('done: ' + '  '.join(f'{k}={v[0]} ({v[1] / 2**30:.2f}->{v[2] / 2**30:.2f} GB)'
                             for k, v in tally.items() if v[0]))
    json.dump({'menus_not_imported': DVD_MENUS_DROPPED,
               'tally': {k: {'count': v[0], 'in_bytes': v[1], 'out_bytes': v[2]}
                         for k, v in tally.items()}},
              open(f'{W}/transcode-import-videos.json', 'w'), indent=1)


if __name__ == "__main__":
    main()
