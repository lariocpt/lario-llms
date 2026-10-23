#!/usr/bin/env python3
"""Print a candidate Radeon registry; never deploy or add live providers.

Usage: python scripts/prepare_placement.py gkm7900xt > /tmp/gkm7900xt.json
The result requires host runtime, credential and admission provisioning before use.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEMENTS = ('gkm7900xt', 'winmax7900xt', 'arcB70')


def prepare(hardware):
    if hardware not in PLACEMENTS:
        raise ValueError('unknown placement')
    placement = json.loads((ROOT / hardware / 'placement.json').read_text())
    if not placement['source_registry']:
        raise ValueError('Arc hardware/runtime/models must be verified before creating a registry')
    reg = json.loads((ROOT / placement['source_registry']).read_text())
    reg.update(host=placement['host'], aliases=[hardware],
               display_name=placement['display_name'],
               port=placement['proposed_port'], backend_port=placement['proposed_backend_port'])
    # Explicit candidate paths prevent accidentally overwriting the active Radeon config.
    reg.update(service=hardware+'.service', config=f'llama-cpp/{hardware}-config.yaml',
               state='.'+hardware+'-model', container=hardware+'-llm',
               backend_key_file=f'/run/lario-admission/{hardware}.backend.key')
    return reg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hardware', choices=PLACEMENTS)
    args = parser.parse_args()
    try:
        reg = prepare(args.hardware)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(reg, indent=2))


if __name__ == '__main__':
    main()
