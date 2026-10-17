#!/usr/bin/env python3
"""Content identity, cheap first.

Two files are the same byte-for-byte only when a full hash says so -- but the
full hash is the last thing to ask, in this order:

1. **size** -- different sizes cannot be the same file, and this alone settles
   most pairs on a media library at no cost;
2. **head hash** (first 1 MiB) -- catches the common "same size, different
   file" case (two videos of identical bitrate and length are not the same
   video) without reading 40 GB;
3. **full BLAKE2b** -- the verdict.

BLAKE2b, not SHA-256, for the dedupe index: it is faster on this CPU and the
use is collision-*resistance-against-accident*, not against an attacker. Where a
digest is stored as an *authority* (a verified copy in the ledger, the encoder's
promote step) the hash is SHA-256, because that is what `runner.sh` compares and
what a verifier will re-compute against.

The cache exists because a run that dies halfway is resumed, and re-hashing
2 TB on the second attempt is how a one-shot deliverable stops being one.
"""
import hashlib
import json
import os

HEAD_BYTES = 1 << 20                       # 1 MiB: enough to separate any two media files
_CHUNK = 1 << 20


def _read_hash(path, algorithm, limit=None):
    digest = hashlib.new(algorithm)
    with open(path, 'rb') as handle:
        remaining = limit
        while True:
            want = _CHUNK if remaining is None else min(_CHUNK, remaining)
            block = handle.read(want)
            if not block:
                break
            digest.update(block)
            if remaining is not None:
                remaining -= len(block)
                if remaining <= 0:
                    break
    return digest.hexdigest()


def sha256(path, limit=None):
    """The authority hash: what the ledger stores and what verify re-computes."""
    return _read_hash(path, 'sha256', limit)


def blake2b(path, limit=None):
    """The index hash: fast, for grouping thousands of files."""
    return _read_hash(path, 'blake2b', limit)


def head_hash(path):
    """Hash of the first `HEAD_BYTES`. Cheap, and enough to reject a size match."""
    return blake2b(path, HEAD_BYTES)


class Duplicates:
    """Groups of byte-identical files, escalating only as far as it must.

    `add()` is cheap and remembers nothing but a path; `groups()` does the work
    and caches the verdicts in `cache_path` so a second run over the same tree
    costs one read.
    """

    def __init__(self, cache_path=None):
        self.paths = []
        self.cache_path = cache_path
        self._head = {}
        self._full = {}
        self._load()

    # -- cache ------------------------------------------------------------
    def _load(self):
        if not self.cache_path or not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return                              # a corrupt cache is no verdict at all
        self._head = data.get('head', {})
        self._full = data.get('full', {})

    def save(self):
        if not self.cache_path:
            return
        leaf = os.path.basename(self.cache_path)
        staging = os.path.join(os.path.dirname(self.cache_path), f'.{leaf}.tmp')
        with open(staging, 'w', encoding='utf-8') as handle:
            json.dump({'head': self._head, 'full': self._full}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, self.cache_path)

    # -- index ------------------------------------------------------------
    def add(self, path, size=None):
        self.paths.append((path, os.path.getsize(path) if size is None else size))

    @staticmethod
    def _stat_key(path):
        """Identity of *this version of this file*, for cache validity.

        The path is part of the key, and so are size and mtime. Dropping the path
        -- keying on `size:mtime` alone -- was a real bug found by the contract
        suite: three different 4096-byte files written inside the same second
        (which is what an rsync or a camera export produces by the thousand) share
        that key, so the second and third inherited the first one's digest and
        were reported as duplicates of it.

        The remaining hole is mtime granularity: replace a file with a different
        one of the same size inside the same second and the cached digest is
        stale. That is why no *deletion* is ever decided from this index. A copy
        re-hashes staging against source (`fsx.copy_file`), and a purge re-hashes
        the survivor and the target before removing anything, so a stale entry can
        at worst make a report untidy -- it cannot make the toolkit delete the
        wrong file.
        """
        try:
            info = os.stat(path)
        except OSError:
            return None
        return f'{os.path.realpath(path)}:{info.st_size}:{int(info.st_mtime)}'

    def _digest_of(self, path, limit, memo):
        token = self._stat_key(path)
        if token is None:
            return None
        found = memo.get(token)
        if found:
            return found
        value = blake2b(path, limit)
        memo[token] = value
        return value

    # -- verdict ----------------------------------------------------------
    def groups(self):
        """Lists of paths that are byte-identical, largest saving first.

        Each returned group is a list of paths ordered by path, so the first
        member is deterministic and a re-run keeps the same survivor.
        """
        by_size = {}
        for path, size in self.paths:
            by_size.setdefault(size, []).append(path)

        out = []
        for size, candidates in sorted(by_size.items(), key=lambda kv: -kv[0]):
            if len(candidates) < 2:
                continue                        # size alone settles it: unique
            by_head = {}
            for path in sorted(candidates):
                head = self._digest_of(path, HEAD_BYTES, self._head)
                if head is not None:
                    by_head.setdefault(head, []).append(path)
            for head, same_head in by_head.items():
                if len(same_head) < 2:
                    continue
                by_full = {}
                for path in same_head:
                    full = self._digest_of(path, None, self._full)
                    if full is not None:
                        by_full.setdefault(full, []).append(path)
                for full, identical in by_full.items():
                    if len(identical) > 1:
                        out.append({'size': size, 'digest': full, 'paths': sorted(identical)})
        self.save()
        return sorted(out, key=lambda group: -(group['size'] * (len(group['paths']) - 1)))
