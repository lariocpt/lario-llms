"""Fetch the pinned Flash Next encoder into the XFS model store."""
import fcntl,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from rtx5080.strata.download import download
state=Path.home()/'.local/state/gpu-migration';state.mkdir(parents=True,exist_ok=True)
with (state/'rtx-vision.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for item in json.loads(Path(__file__).with_name('vision_weights.json').read_text())['files']:download(item)
