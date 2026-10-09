#!/usr/bin/env python3
"""Restore the chat service and admission after an encoder job (runner trap, controller repair or cancel).

Idempotent: serialized by restore.lock; the service is only started when it was
active before the job borrowed the card (was_chat_active), and skipped when a
previous restore already started it.
"""
import contextlib
import fcntl
import io
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from shared import modelctl


def main():
    job = json.loads(Path(sys.argv[1]).read_text())
    reg = json.loads((REPO / 'rtx5080/models.json').read_text())
    modelctl.load_runtime(reg)
    with open(HERE / 'restore.lock', 'w') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        active = subprocess.run(['systemctl', '--user', 'is-active', reg['service']],
                                capture_output=True).returncode == 0
        if job.get('was_chat_active') and not active:
            subprocess.run(['systemctl', '--user', 'start', reg['service']], check=True,
                           stdout=subprocess.DEVNULL)
            active = True
        if job.get('was_chat_active') and active:
            with contextlib.redirect_stdout(io.StringIO()):
                modelctl.warm(reg, reg['aliases'][0])
        modelctl.admission_admin(reg, 'resume')


if __name__ == '__main__':
    main()
