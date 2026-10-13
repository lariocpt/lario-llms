"""pCloud public-link access: one-time download URLs and ranged transfers.

A public-link code resolves to a short-lived host+path pair through
``getpublinkdownload``.  That link must be requested per attempt: it expires
within minutes, so a link fetched before a long queue is the one thing that
fails halfway through a multi-hour job.

Transfers go through curl rather than urllib so that resume (``-C -``), stall
detection (``--speed-limit``) and transient-retry are handled by something
battle-tested.  curl is only asked to write a ``.part`` file; renaming into the
library is the caller's decision after it has verified the byte size.
"""
import json
import subprocess
import urllib.parse
import urllib.request

API = 'https://api.pcloud.com/getpublinkdownload'
USER_AGENT = 'curl/8.12'
CONNECT_TIMEOUT = 25


class PcloudError(RuntimeError):
    """A public link could not be resolved, or a transfer failed."""


def download_url(code, fileid, host_index=0):
    """Resolve one file of a public folder to a directly-fetchable https URL."""
    query = urllib.parse.urlencode({'code': code, 'fileid': fileid, 'forcedownload': 1})
    request = urllib.request.Request(API + '?' + query, headers={'User-Agent': USER_AGENT})
    try:
        body = urllib.request.urlopen(request, timeout=60).read().decode()
    except OSError as error:
        raise PcloudError('link lookup failed: ' + str(error)[:160]) from None
    try:
        data = json.loads(body)
    except ValueError:
        raise PcloudError('link lookup returned non-JSON') from None
    if data.get('result') != 0:
        raise PcloudError('pcloud result %s: %s' % (data.get('result'), data.get('errmsg')))
    hosts = data.get('hosts') or []
    if not hosts or not data.get('path'):
        raise PcloudError('pcloud returned no host/path for fileid %s' % fileid)
    return 'https://' + hosts[host_index % len(hosts)] + data['path']


def transfer(url, part, resume=True):
    """Fetch url into ``part`` (never the destination itself).  Returns bytes on disk.

    With ``resume`` the transfer continues an existing ``.part``; if the server
    refuses the range (curl 33) the partial file is discarded and the whole file
    is re-fetched, which is the only safe reading of a rejected resume.
    """
    command = ['curl', '-fsS', '--connect-timeout', str(CONNECT_TIMEOUT),
               '--retry', '3', '--retry-delay', '2',
               '--speed-limit', '1024', '--speed-time', '60']
    if resume:
        command += ['-C', '-']
    command += ['-o', part, url]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 33 and resume:
        subprocess.run(['rm', '-f', part])
        return transfer(url, part, resume=False)
    if result.returncode:
        raise PcloudError('curl %d: %s' % (result.returncode, result.stderr.strip()[:180]))
    return _size(part)


def _size(path):
    import os
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
