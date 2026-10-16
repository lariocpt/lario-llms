"""Photos roots, under the short names the existing scripts already use.

The values live in `media/core/config.py`. They are re-exported here so a script
can be run straight out of this directory with nothing installed:

    python3 media/photos/plan_import.py

and so that a machine with different paths needs one environment change, not a
sweep through 44 files. `LIB` here means the *photo* library; the music corpus
has its own `paths.py` where `LIB` means the music library.

    W       scratch: jsonl audits, manifests, hash caches for this job
    LIB     the photo library the pass files into
    VIDLIB  the video library (photos that carry a live-photo video live here)
    HHD     the external-drive source still being merged in
"""
import os
import sys

_MEDIA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _MEDIA not in sys.path:
    sys.path.insert(0, _MEDIA)

from core.config import HHD              # noqa: E402,F401
from core.config import PHOTO_BACKUP as BACKUP  # noqa: E402,F401
from core.config import PHOTO_BACKUP_PHOTOS as BACKUP_PHOTOS  # noqa: E402,F401
from core.config import PHOTO_LIB as LIB  # noqa: E402,F401
from core.config import PHOTO_STAGING as STAGING  # noqa: E402,F401
from core.config import PHOTO_WORK as W  # noqa: E402,F401
from core.config import VIDEO_LIB as VIDLIB  # noqa: E402,F401
