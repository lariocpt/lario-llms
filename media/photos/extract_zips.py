#!/usr/bin/env python3
"""Expand the two archives left in the source trees into a staging folder so their

contents can be deduped and imported like any other source file.

Nothing is deleted from the archives here, and nothing is written outside the
staging folder. Nested archives (Archive.zip holds Marie.zip and Paris.zip) are
expanded in place into a directory of their own; the container entry itself is
recorded, not treated as content.

AppleSingle/AppleDouble junk (__MACOSX/, ._*, .DS_Store, Thumbs.db) is skipped.

Writes:
  zip-extract/<zip name>/<entry path>      the expanded bytes
  zip-staging.json                         staging dir -> archive provenance
  zip-provenance.jsonl                     staged file -> where it really came from

usage: python3 extract_zips.py
"""

# This file is a COMMAND, not a library: importing it used to run the pass, which
# is how a `--help` typo came to overwrite a finished plan. Run it instead:
#     python3 media/photos/extract_zips.py
if __name__ != "__main__":
    raise SystemExit(__file__ + " is a command; run it, do not import it")
import json
import os
import shutil
import zipfile

W = '/home/lario/photos-reorg-work'
STAGE = f'{W}/zip-extract'
from paths import HHD
TREE = 'Photosusa'
ARCHIVES = [f'{HHD}/{TREE}/photos/Archive.zip', f'{HHD}/{TREE}/photos/Marie/Marie.zip']
JUNKNAME = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.localized'}


def junk(name):
    b = name.rsplit('/', 1)[-1]
    return (name.startswith('__MACOSX/') or b.startswith('._') or b in JUNKNAME
            or b.startswith('._'))


def safe(rel):
    """Reject anything that would escape the staging directory."""
    rel = rel.replace('\\', '/').lstrip('/')
    parts = [p for p in rel.split('/') if p not in ('', '.')]
    return None if any(p == '..' for p in parts) or not parts else '/'.join(parts)


def expand(zp, stage_root, prov, prefix, stats, depth=0):
    """Extract one archive into stage_root; recurse into nested archives."""
    with zipfile.ZipFile(zp) as z:
        for info in z.infolist():
            rel = safe(info.filename)
            if rel is None or info.is_dir():
                continue
            if junk(rel):
                stats['junk_skipped'] += 1
                continue
            data = z.read(info)
            if rel.lower().endswith('.zip'):
                # a container, not content: expand it as its own directory
                tmp = os.path.join(STAGE, '.nested.tmp')
                with open(tmp, 'wb') as fh:
                    fh.write(data)
                inner_root = os.path.join(stage_root, os.path.splitext(rel)[0])
                tag = prefix + rel                      # Archive.zip::Marie/Marie.zip
                inner = {'files': 0, 'bytes': 0, 'junk_skipped': 0}
                try:
                    expand(tmp, inner_root, prov, tag + '::', inner, depth + 1)
                    rec = {'container': tag, 'bytes': len(data), 'entries': inner['files'],
                           'entry_bytes': inner['bytes']}
                except zipfile.BadZipFile as e:
                    rec = {'container': tag, 'bytes': len(data), 'error': str(e)[:80]}
                stats['nested'] = stats.get('nested', []) + [rec]
                stats['files'] += inner['files']
                stats['bytes'] += inner['bytes']
                stats['junk_skipped'] += inner['junk_skipped']
                os.remove(tmp)
                continue
            out = os.path.join(stage_root, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, 'wb') as fh:
                fh.write(data)
            prov[out] = f'{prefix}{rel}'
            stats['files'] += 1
            stats['bytes'] += len(data)
    return stats['files']


def main():
    if os.path.exists(STAGE):
        raise SystemExit(f'{STAGE} already exists - refusing to overwrite staging')
    os.makedirs(STAGE)
    staging, prov = {}, {}
    for zp in ARCHIVES:
        name = os.path.splitext(os.path.basename(zp))[0]
        root = os.path.join(STAGE, name)
        os.makedirs(root)
        stats = {'files': 0, 'bytes': 0, 'junk_skipped': 0}
        with zipfile.ZipFile(zp) as z:
            total = len([i for i in z.infolist() if not i.is_dir()])
        n = expand(zp, root, prov, f'{name}.zip::', stats)
        staging[name] = {'dir': root, 'zip': zp, 'tree': TREE,
                         'zip_rel': os.path.relpath(zp, f'{HHD}/{TREE}'),
                         'archive_entries': total, 'extracted_files': stats['files'],
                         'extracted_bytes': stats['bytes'],
                         'junk_skipped': stats['junk_skipped'],
                         'nested': stats.get('nested', [])}
        print(f'{name}.zip: {total} entries -> {stats["files"]} files '
              f'{stats["bytes"] / 2**20:.1f} MB, junk skipped {stats["junk_skipped"]}, '
              f'nested archives {len(stats.get("nested", []))}')
        for nest in stats.get('nested', []):
            print(f'    nested {nest["container"]} '
                  f'{nest.get("entries", 0)} entries'
                  f'{nest.get("error", "")}')
    json.dump(staging, open(f'{W}/zip-staging.json', 'w'), indent=1)
    with open(f'{W}/zip-provenance.jsonl', 'w') as fh:
        for path, src in sorted(prov.items()):
            fh.write(json.dumps({'staged': path, 'provenance': src}) + '\n')
    tot = sum(v['extracted_bytes'] for v in staging.values())
    print(f'\nstaged {sum(v["extracted_files"] for v in staging.values())} files '
          f'{tot / 2**30:.2f} GiB under {STAGE}')
    print('disk free on /home:', shutil.disk_usage('/home').free / 2**30, 'GiB')


if __name__ == "__main__":
    main()
