#!/usr/bin/env python3
"""Backend ExecStartPre: render the static fixed-profile configuration privately."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared import modelctl
from shared.serving.catalog import HARDWARE, render_backend
from shared.serving.state import off_marker

if __name__=='__main__':
    hardware = sys.argv[1]
    if hardware not in HARDWARE:
        raise SystemExit('unknown hardware')
    reg = json.loads((ROOT/hardware/'models.json').read_text())
    modelctl.load_runtime(reg)
    if off_marker(reg).exists():
        raise SystemExit('hardware is Off')
    path = ROOT/reg['config']
    text = render_backend(reg)
    if not path.exists() or path.read_text()!=text:
        modelctl.atomic(path,text)
