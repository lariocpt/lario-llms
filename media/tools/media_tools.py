#!/usr/bin/env python3
"""Media-organising MCP: library state, the job catalogue, and the two reviewed
passes that are safe to hand to an agent.

The corpora beside this file move real files, so this server is deliberately
narrow:

* Read-only by default. The mutating verb is not registered unless
  ``LARIO_MEDIA_ALLOW_JOBS=1`` is in the server's environment.
* **There is no delete verb here, and no job accepts a path.** A job is a script
  in this directory with a fixed argv; the only arguments accepted are the flags
  in its schema, so nothing a caller passes can become a shell command.
* Every exposed pass plans before it acts, and defaults to its dry run: writing
  needs ``apply: true``. Passes with no dry run (the repair and delete chain) are
  listed under ``manual`` with the command to run by hand, and cannot be run here.
* Encoding is not exposed either: ``lario_encoder`` owns the RTX 5080, and two
  owners of one card is how an encode and a chat model collide.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

MEDIA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MEDIA))
from core import config  # noqa: E402

ALLOW_JOBS = os.getenv('LARIO_MEDIA_ALLOW_JOBS', '0') == '1'
TIMEOUT = int(os.getenv('LARIO_MEDIA_TIMEOUT', '900'))

# name -> fixed argv in this repo, what it touches, and the flags it accepts.
JOBS = {
    'photos_plan': {
        'argv': ['photos/plan_import.py'],
        'does': 'Recompute the photo/video import plan and write it to PHOTO_PLAN. '
                'Writes the plan file only; refuses a zero-record write over a '
                'non-empty plan unless PLAN_ALLOW_SHRINK=1, and keeps .prev.',
        'touches': 'the plan file',
        'flags': {'dry': '--dry'},
    },
    'photos_video_import': {
        'argv': ['photos/transcode_import_videos.py'],
        'does': 'Transcode the videos the plan queues and file them into the video '
                'library. test=N encodes N seconds of each job and keeps nothing.',
        'touches': 'the video library',
        'flags': {'dry': '--dry', 'limit': '--limit', 'workers': '--workers',
                  'test': '--test'},
    },
}

# Reviewed but not runnable here: destructive, irreversible, or GPU-owning.
MANUAL = [
    {'name': 'video_encode',
     'command': 'python3 media/video/enc_hevc.py --root DIR --log run.jsonl --qp 23',
     'why': 'hevc_nvenc is exclusive; lario_encoder owns the RTX 5080.'},
    {'name': 'photos_delete_chain',
     'command': 'prove_deletes.py -> rebuild_deletes.py -> freeze_deletes.py -> '
                'delete_source_duplicates.py -> audit_deletes.py -> verify_final.py',
     'why': 'Removes library entries. Runs only with the owner watching, and the '
            'gates must be green first; nothing in this server may call it.'},
    {'name': 'music_import',
     'command': 'python3 media/music/mini_import.py [--apply]',
     'why': 'Needs mutagen, which media/.venv does not have yet. Dry unless '
            '--apply: it writes the import plan and moves nothing until told. '
            'Run it against a staged copy first.'},
    {'name': 'sanderson_shelf_merge',
     'command': 'python3 media/audiobooks/merge_sanderson.py [--apply|--undo]',
     'why': 'Restructures a shelf the owner reads in an app; already applied '
            '2026-10-14 (395 files), so it is kept for a future shelf.'},
]


def _space(path):
    """Free space on the filesystem holding `path`, without walking it."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.exists():
        return None
    free = os.statvfs(str(probe))
    return {'root': str(path), 'exists': Path(path).is_dir(),
            'free_gb': round(free.f_bavail * free.f_frsize / 2 ** 30, 1)}


def _newest(work):
    root = Path(work)
    if not root.is_dir():
        return None
    files = [p for p in root.iterdir()
             if p.is_file() and p.suffix in ('.jsonl', '.json')
             and 'plan' not in p.name]
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return {'file': str(newest), 'bytes': newest.stat().st_size}


def _plan():
    """The hand-edited plan, as data: count, bytes, and whether it is still sane."""
    path = Path(config.PHOTO_PLAN)
    if not path.is_file():
        return {'file': str(path), 'present': False}
    out = {'file': str(path), 'present': True, 'bytes': path.stat().st_size}
    try:
        out['records'] = len(json.loads(path.read_text()))
    except ValueError as error:
        out['error'] = str(error)[:120]
    return out


def status(_args):
    return {
        'libraries': {name: _space(getattr(config, name))
                      for name in ('PHOTO_LIB', 'PHOTO_STAGING', 'VIDEO_LIB',
                                   'MUSIC_LIB', 'MUSIC_STAGE', 'MOVIES', 'SERIES',
                                   'AUDIOBOOKS', 'BOOKS')},
        'plan': _plan(),
        'evidence': {domain: _newest(work)
                     for domain, work in (('photos', config.PHOTO_WORK),
                                          ('music', config.MUSIC_WORK),
                                          ('video', config.VIDEO_WORK))},
        'jobs_runnable': sorted(JOBS),
        'jobs_gated': sorted(JOBS) if not ALLOW_JOBS else [],
        'gate': {'LARIO_MEDIA_ALLOW_JOBS': ALLOW_JOBS},
        'deletes_available': False,
    }


def jobs(_args):
    return {'runnable': [{'name': name, 'command': ' '.join(job['argv']),
                          'does': job['does'], 'touches': job['touches'],
                          'flags': sorted(job['flags']),
                          'gated': not ALLOW_JOBS} for name, job in sorted(JOBS.items())],
            'manual': MANUAL,
            'note': 'apply defaults to false: a job runs its dry run unless '
                    'apply=true is passed.'}


def run(args):
    if not ALLOW_JOBS:
        raise RuntimeError('job execution is off; start the server with '
                           'LARIO_MEDIA_ALLOW_JOBS=1')
    name = args['name']
    job = JOBS.get(name)
    if job is None:
        raise RuntimeError(f'no such job: {name}. Available: '
                           + ', '.join(sorted(JOBS)) + '. Others are manual-only.')
    options = args.get('options') or {}
    apply_writes = bool(args.get('apply'))
    unknown = set(options) - set(job['flags'])
    if unknown:
        raise RuntimeError('options not accepted by ' + name + ': '
                           + ', '.join(sorted(unknown)))
    argv = [sys.executable, str(MEDIA / job['argv'][0])]
    for key, flag in job['flags'].items():
        if key not in options:
            continue
        value = options[key]
        if isinstance(value, bool):
            if value:
                argv.append(flag)
        elif type(value) is int and value >= 0:
            argv += [flag, str(value)]
        else:
            raise RuntimeError(f'{name}: {key} must be a bool or a non-negative int')
    if 'dry' in job['flags'] and not apply_writes and '--dry' not in argv:
        argv.append('--dry')       # a job never writes unless the caller says so
    done = subprocess.run(argv, cwd=str(MEDIA), capture_output=True, text=True,
                          timeout=TIMEOUT)
    return {'command': ' '.join(argv[1:]), 'returncode': done.returncode,
            'apply': apply_writes, 'stdout': done.stdout[-3000:],
            'stderr': done.stderr[-800:]}


TOOLS = [
    {'name': 'media_status',
     'description': 'Where every media library resolves (overridable by LARIO_* env), free space on each, the photo import plan\'s record count and whether it still parses, and the newest evidence file per domain. Read-only; it never walks a library or counts files.',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'readOnlyHint': True}},
    {'name': 'media_jobs',
     'description': 'The passes this toolkit can run, what each touches, its flags, and the reviewed-but-manual-only ones (encode, the photo delete chain, music import, shelf merge) with the reason each is not runnable here. Read-only.',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'readOnlyHint': True}}]
if ALLOW_JOBS:
    TOOLS.append(
        {'name': 'media_run',
         'description': 'Run a declared media pass by name with a fixed argv: photos_plan (writes only the plan file) or photos_video_import (files transcoded video into the video library). Always plans first -- apply:false (the default) forces the dry run. No path arguments, and no way to delete anything.',
         'inputSchema': {'type': 'object', 'properties': {
             'name': {'type': 'string', 'enum': sorted(JOBS)},
             'apply': {'type': 'boolean', 'description': 'Allow the pass to write. Default false = dry run.', 'default': False},
             'options': {'type': 'object', 'description': 'Flags from the job\'s schema (dry/limit/workers/test). Nothing else is accepted.'}},
             'required': ['name'], 'additionalProperties': False},
         'annotations': {'destructiveHint': True, 'openWorldHint': False}})

HANDLERS = {'media_status': status, 'media_jobs': jobs, 'media_run': run}


def call(name, args):
    # gate-aware on purpose: a gated tool is not in TOOLS, and answering with
    # StopIteration from next() would report an empty, unhelpful error.
    tool = next((tool for tool in TOOLS if tool['name'] == name), None)
    if tool is None or not isinstance(args, dict) or name not in HANDLERS:
        raise RuntimeError('unknown tool ' + str(name)
                           + ' (not offered by this server, or gated off)')
    if set(args) - set(tool['inputSchema']['properties']):
        raise RuntimeError('unexpected arguments for ' + name)
    return HANDLERS[name](args)


def main():
    for line in sys.stdin:
        identifier = None
        try:
            request = json.loads(line)
            identifier = request.get('id')
            if identifier is None:
                continue
            method = request.get('method')
            if method == 'initialize':
                version = request.get('params', {}).get('protocolVersion', '2024-11-05')
                result = {'protocolVersion': version if version in ('2024-11-05', '2025-03-26', '2025-06-18') else '2024-11-05',
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': 'lario-media', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                params = request['params']
                try:
                    data = call(params['name'], params.get('arguments', {}))
                    result = {'content': [{'type': 'text', 'text': json.dumps(data)}],
                              'isError': False}
                except Exception as error:
                    result = {'content': [{'type': 'text', 'text': str(error)[:500]}],
                              'isError': True}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': identifier,
                                  'error': {'code': -32601, 'message': 'Method not found'}}),
                      flush=True)
                continue
            print(json.dumps({'jsonrpc': '2.0', 'id': identifier, 'result': result}),
                  flush=True)
        except Exception as error:
            print(json.dumps({'jsonrpc': '2.0', 'id': identifier,
                              'error': {'code': -32600, 'message': str(error)[:500]}}),
                  flush=True)


if __name__ == '__main__':
    main()
