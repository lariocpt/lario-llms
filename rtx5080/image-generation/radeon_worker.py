"""Select the registered discrete Radeon before importing the ROCm runtime."""
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from shared.gpu import radeon_device


def main():
    registry = json.loads((REPO / 'gdp7900xt/models.json').read_text())
    device = radeon_device(registry['device_identity'])
    os.environ['ROCR_VISIBLE_DEVICES'] = 'GPU-' + device['unique_id']
    worker = Path.home() / '.local/share/lario-model-runtimes/image-generation/gdp7900xt/ComfyUI/main.py'
    os.chdir(worker.parent)
    os.execv(sys.executable, [sys.executable, str(worker), *sys.argv[1:]])


if __name__ == '__main__':
    main()
