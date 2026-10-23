# Model backend recovery

Install on Bigcachy, l-dev-ai and mini-mobile after syncing this repository:

```sh
python3 shared/install_backend_watch.py
systemctl --user status lario-backend-watch.timer
journalctl --user -u lario-backend-watch.service -n 30 --no-pager
```

The user timer runs 30 seconds after boot and every 60 seconds afterwards, with
small random jitter. It retries enabled local admission and backend services that
are inactive or failed. It rechecks device identity on each attempt, so a GPU
which becomes available late can recover without another reboot. The B70 startup
check also allows 60 seconds for its render node to become ready.

Off intent, a boot-local Stop, deployment holds, masks and disabled units remain
in force. Active/loading/deactivating units are never restarted. A healthy but
busy backend is untouched. The watcher does not activate profiles or generate
inference. A running but hung service is reported by existing model monitoring;
this watcher deliberately does not kill uncertain client work.

Bigcachy and l-dev-ai also ask each other over their existing SSH connection to
run the same local-only reconciliation. The remote call cannot recurse. If a
peer is down or the link is unavailable, local recovery still completes and the
next timer tick retries. No peer is required to boot and no credentials are
copied. Each host applies its own Off/device/service checks.

To stop automatic recovery, disable `lario-backend-watch.timer`. Use the existing
model controls to switch hardware Off; do not rely on stopping a unit directly
while its administrative state remains enabled and On.
