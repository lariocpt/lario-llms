# gkm7900xt — Geekom external Radeon

Prepared placement of the existing RX 7900 XT on l-dev-ai through an adapter in
the spare NVMe slot. Not installed or advertised yet. This is independent of the
Geekom APU's `geekom` service.

`placement.json` owns the intended host, name and storage. Generate candidate
model configuration with `python scripts/prepare_placement.py gkm7900xt`.
Models inherit [the current Radeon registry](../7900xt/models.json).

See [activation and migration](../docs/hardware-transition-2026-10-23.md).
