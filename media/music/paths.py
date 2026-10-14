"""Music roots, under the short names the existing scripts already use.

Values live in `media/core/config.py`; see `media/photos/paths.py` for why the
shim exists. Note that `LIB` means the *music* library here, which is the one
name that means something different in each domain -- importing the wrong
`paths` would point a copy pass at the photos.

    STAGE     the mini-player staging area being sorted into the library
    LIB       the music library (Navidrome's configured root)
    DB        Navidrome's index, opened read-only
    FALLBACK  where a file with no trustworthy artist/album goes, for review
"""
import os
import sys

_MEDIA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _MEDIA not in sys.path:
    sys.path.insert(0, _MEDIA)

from core.config import MUSIC_LIB as LIB  # noqa: E402,F401
from core.config import MUSIC_WORK as WORK  # noqa: E402,F401
from core.config import NAVIDROME_DB as DB  # noqa: E402,F401
from core.config import PRESERVED_MINI  # noqa: E402,F401

STAGE = os.environ.get("LARIO_MUSIC_STAGE", "/mnt/xfs/staging-mini-music")
FALLBACK = "_Unsorted/mini-mobile"
