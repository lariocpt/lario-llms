#!/usr/bin/env python3
"""Re-scan the three trees into JSON so every later step is evidence-based.


Lost in the /tmp wipe: meta.json, plan.json and the executed manifests. The
trees themselves are intact, so re-derive what the pipeline knew:
  meta_backup.json  everything in the pre-change backup (ground truth for
                    "what existed", used to prove deletes and rebuild moves)
  meta_new.json     the staged photo tree
  meta_videos.json  the videos still sitting in the old tree
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/rescan.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

EXIFTOOL = '/home/lario/.local/bin/exiftool'
TAGS = ['-G0', '-m', '-q', '-j', '-api', 'LargeFileSupport=1',
        '-file:FileType', '-file:FileTypeExtension', '-file:MIMEType',
        '-System:FileSize', '-System:FileModifyDate', '-System:FilePermissions',
        '-File:ImageWidth', '-File:ImageHeight', '-Composite:ImageSize',
        '-Composite:Duration', '-Composite:Rotation',
        '-ExifIFD:DateTimeOriginal', '-ExifIFD:DateTimeDigitized',
        '-ExifIFD:OffsetTimeOriginal', '-QuickTime:CreateDate',
        '-QuickTime:ModifyDate', '-Track1:MediaCreateDate',
        '-GPSLatitude', '-GPSLongitude', '-ExifIFD:Orientation',
        '-Apple:ContentIdentifier', '-XMP:ContentIdentifier',
        '-QuickTime:MovieHeaderWidth', '-QuickTime:MovieHeaderHeight',
        '-QuickTime:VideoFrameRate', '-Composite:BitsPerSample']
BATCH = 700


def scan(root, workers=6):
    paths = []
    for dirpath, dirs, files in os.walk(root):
        for fn in files:
            paths.append(os.path.join(dirpath, fn))
    paths.sort()
    out = {}

    def one(chunk):
        r = subprocess.run([EXIFTOOL] + TAGS + chunk,
                           capture_output=True, text=True)
        try:
            recs = json.loads(r.stdout or '[]')
        except Exception:
            recs = []
            for p in chunk:            # fall back to one-at-a-time
                r = subprocess.run([EXIFTOOL] + TAGS + [p],
                                   capture_output=True, text=True)
                try:
                    recs += json.loads(r.stdout or '[]')
                except Exception:
                    pass
        return {os.path.relpath(x['SourceFile'], root): x for x in recs
                if 'SourceFile' in x}

    chunks = [paths[i:i + BATCH] for i in range(0, len(paths), BATCH)]
    with ThreadPoolExecutor(workers) as ex:
        for part in ex.map(one, chunks):
            out.update(part)
    print(f'{root}: {len(paths)} files on disk, {len(out)} records', flush=True)
    return out


if __name__ == '__main__':
    root, dest = sys.argv[1], sys.argv[2]
    data = scan(root)
    tmp = dest + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh)
    os.replace(tmp, dest)
    print('wrote', dest, flush=True)
