#!/usr/bin/env python3
"""The only place in the toolkit that writes or removes a byte.

Everything here is deliberately boring and deliberately gated:

* **Copies are atomic and verified.** Content is written to a dot-named staging
  file in the *destination directory*, fsync'd, hashed, and only then
  `os.replace`'d over the final name. A run that dies leaves a stray `.tmp` and
  an untouched original -- never a truncated file wearing the original's name.
* **Symlinks are never followed.** `shutil.copyfile(..., follow_symlinks=False)`
  is not the default, and a source tree that arrived from an external drive can
  contain a link to somewhere it does not own.
* **Deletion needs a ledger row.** `remove()` raises `UnauthorisedDelete` unless
  the ledger holds an *authorised* delete row for that exact path in this run,
  and an authorised row only exists once a verified copy of that content is
  known to exist elsewhere (§4.2). The `--delete-sources` flag authorises the
  phase; the ledger authorises each file.
* **No recursive delete exists here at all.** Not because it would never be
  useful, but because a single wrong root argument is unrecoverable and nothing
  in this toolkit needs it.

Reflink (`FICLONE`) is attempted only when asked and only on a same-device
pair, and a failed reflink is a *silent* fallback to a copy -- it is an
optimisation, never a correctness decision. Where the copy is the fallback for a
dedupe that would have been a hardlink across devices, the caller counts those
bytes as **relocated**, never reclaimed.
"""
import fcntl
import os
import shutil

from core.digest import sha256

# _IOW(0x94, 23, int) -- the btrfs-extent clone ioctl, honoured by btrfs, XFS
# (with the reflink feature) and overlayfs-on-clone-supporting-backends.
FICLONE = 0x40049423
TMP_PREFIX = '.mediatool-'


class UnauthorisedDelete(RuntimeError):
    """Raised when a delete has no authorising ledger row. Never caught quietly."""


def free_bytes(path):
    """Bytes available to *this* user at `path` (root-reserved blocks excluded)."""
    return shutil.disk_usage(path).free


def total_bytes(path):
    return shutil.disk_usage(path).total


def device_of(path):
    """The device id holding `path`, resolved through whatever exists above it.

    Used to answer one question only: can a hardlink or a reflink exist between
    two paths. They cannot across devices, and a plan that assumed otherwise
    would either fail mid-run or, worse, quietly succeed at something the owner
    read as a space saving.
    """
    candidate = os.path.realpath(path)
    while True:
        try:
            return os.stat(candidate).st_dev
        except OSError:
            parent = os.path.dirname(candidate)
            if parent == candidate:
                raise
            candidate = parent


def same_device(a, b):
    try:
        return device_of(a) == device_of(b)
    except OSError:
        return False


def try_reflink(src, dst):
    """Attempt a clone; True only when the kernel confirms one happened."""
    if not same_device(src, dst):
        return False
    try:
        with open(src, 'rb') as source, open(dst, 'wb') as target:
            fcntl.ioctl(target.fileno(), FICLONE, source.fileno())
        return True
    except OSError:
        return False


def copy_file(src, dst, *, reflink=False, verify=True, digest=None):
    """Copy `src` to `dst` so a crash cannot leave a half-written `dst`.

    Returns a receipt: bytes, sha256 (the authority hash, same as the encoder's
    promote step), the method used, and whether it was verified. `digest` skips
    re-hashing the source when the caller already knows it -- which is the whole
    point of the dedupe index.
    """
    leaf = os.path.basename(dst)
    directory = os.path.dirname(dst) or '.'
    os.makedirs(directory, exist_ok=True)
    staging = os.path.join(directory, f'{TMP_PREFIX}{leaf}')
    method = 'copy'
    try:
        if reflink and try_reflink(src, staging):
            method = 'reflink'
        else:
            shutil.copyfile(src, staging, follow_symlinks=False)
            shutil.copystat(src, staging, follow_symlinks=False)
        handle = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)
        target_digest = sha256(staging)
        if verify:
            source_digest = digest or sha256(src)
            if source_digest != target_digest:
                raise OSError(f'copy verify mismatch for {dst}: source {source_digest} '
                              f'copy {target_digest}')
        os.replace(staging, dst)
    finally:
        if os.path.exists(staging):
            # Only the failure path reaches here: on success os.replace moved it.
            try:
                os.remove(staging)
            except OSError:
                pass
    size = os.path.getsize(dst)
    return {'bytes': size, 'sha256': target_digest, 'method': method,
            'verified': bool(verify), 'device': device_of(dst)}


def authorising(ledger, run_id, path):
    """The authorised delete row for `path` in `run_id`, or None.

    `realpath` on both sides: a row written for `/mnt/a/x` must not authorise the
    deletion of `/mnt/b/x` reached through a symlink, and vice versa.
    """
    return ledger.authorised_delete(run_id, os.path.realpath(path))


def remove(ledger, run_id, path):
    """Delete one file the ledger authorised. Everything else raises.

    Four conditions have to hold, and the reason matters more than the fact:
      1. `path` is a regular file -- no directories, ever;
      2. this run holds an `authorised` delete row naming its resolved path;
      3. a verified copy of its content exists elsewhere (the ledger proves it,
         because that is what made the row authorisable);
      4. the row is not already `done`, which is what makes a replay a no-op.
    """
    target = os.path.realpath(path)
    if os.path.islink(path) or not os.path.isfile(target):
        raise UnauthorisedDelete(f'{path} is not a regular file; core.fsx never removes '
                                 f'directories or symlinks')
    row = authorising(ledger, run_id, target)
    if row is None:
        raise UnauthorisedDelete(
            f'no authorised delete row for {target} in run {run_id}. Deletion needs a '
            f'verified copy elsewhere and --delete-sources named explicitly (PLAN §4.2).')
    current = sha256(target)
    if current != row['src_sha256']:
        # The plan said "these bytes are safe to lose because they survive at
        # dst". If the bytes changed after the plan was reviewed, that argument is
        # about a file that no longer exists -- so this is a refusal, not a warning.
        raise UnauthorisedDelete(
            f'{target} changed since the plan was written (planned '
            f'{row["src_sha256"][:12]}, now {current[:12]}); refusing to delete content '
            f'no one reviewed')
    os.remove(target)
    ledger.mark_delete_done(row['id'])
    return {'bytes': row['bytes'], 'path': target, 'sha256': current}
