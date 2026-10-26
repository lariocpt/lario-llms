#!/usr/bin/env bash
# Install mini-mobile's next-boot OCuLink guard. Does not reset/reboot the GPU.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run this installer with sudo.' >&2; exit 1; }
[ "$(hostname -s)" = cachyos-mini-mobile ] || { echo 'mini-mobile only' >&2; exit 1; }
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v mkinitcpio >/dev/null
# A module-wide NVIDIA option is appropriate only while this is the sole NVIDIA GPU.
python3 - <<'PY'
from pathlib import Path
cards=[]
for p in Path('/sys/bus/pci/devices').iterdir():
    try:
        if (p/'vendor').read_text().strip()=='0x10de' and (p/'class').read_text().strip().startswith('0x03'):
            cards.append((p/'device').read_text().strip())
    except OSError:
        continue
if cards != ['0x2489']:
    raise SystemExit('Expected only the registered RTX 3060 Ti; refusing a global NVIDIA option')
PY
backup_dir="/var/lib/lario-oculink-guard/backups/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup_dir"
files=(/usr/local/libexec/lario-oculink-guard /etc/modprobe.d/99-lario-oculink-power.conf /etc/udev/rules.d/99-lario-oculink-power.rules /etc/systemd/system/lario-oculink-guard.service /usr/lib/systemd/system-sleep/lario-oculink-resume)
for dest in "${files[@]}"; do
    if [ -e "$dest" ]; then cp --parents -a "$dest" "$backup_dir/"; fi
done
install -D -m 755 "$source_dir/oculink_guard.py" "${files[0]}"
install -D -m 644 "$source_dir/guardrails/99-lario-oculink-power.conf" "${files[1]}"
install -D -m 644 "$source_dir/guardrails/99-lario-oculink-power.rules" "${files[2]}"
install -D -m 644 "$source_dir/guardrails/lario-oculink-guard.service" "${files[3]}"
install -D -m 755 "$source_dir/guardrails/lario-oculink-resume" "${files[4]}"
systemctl daemon-reload
udevadm control --reload-rules
systemctl enable lario-oculink-guard.service
# NVIDIA is loaded from initramfs on this host; modprobe.d alone is insufficient.
mkinitcpio -P
printf 'Installed for next boot. No live GPU reset or reboot performed. Backups: %s\n' "$backup_dir"
