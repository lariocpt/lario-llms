#!/usr/bin/env python3
"""ExecCondition for boot-local manual stop intent; performs no service action."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.lifecycle import stop_marker
from shared.serving.state import off_marker

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('geekom', '7900xt', 'rtx5080', 'arcB70'):
        sys.exit(2)
    registry = json.loads((ROOT/sys.argv[1]/'models.json').read_text())
    sys.exit(1 if stop_marker(registry).exists() or off_marker(registry).exists() else 0)
