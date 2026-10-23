"""Consumer-safe planned placements, excluded from active serving capacity."""
import json

from scripts.prepare_placement import PLACEMENTS, ROOT, prepare
from shared.serving.catalog import profiles, public, compact_hardware_name


def inventory():
    entries = []
    for hardware in PLACEMENTS:
        p = json.loads((ROOT/hardware/'placement.json').read_text())
        entries.append({k: p[k] for k in (
            'hardware', 'display_name', 'host', 'status', 'connection', 'physical_resource')})
        entry = entries[-1]
        entry['display_name'] = compact_hardware_name(entry['display_name'])
        entry['exclusive_with'] = p.get('exclusive_with', [])
        entry['live_hardware_id'] = p.get('live_hardware_id')
        entry['profiles'] = ([public(model) for model in profiles(prepare(hardware)).values()]
                             if p['source_registry'] else [])
    return entries


if __name__ == '__main__':
    target = ROOT/'shared/serving/web/placements.json'
    target.write_text(json.dumps(inventory(), indent=2)+'\n')
    entries = profiles(prepare('arcB70'))
    models = {key: {'name':p['name'], 'tool_call':True,
                   'limit':{'context':p['context']-4096,'output':8192},
                   'modalities':{'input':['text'],'output':['text']}}
              for key,p in entries.items()}
    (ROOT/'arcB70/opencode.prepared.json').write_text(json.dumps({
        'disabled_providers':['arcB70'],
        'provider':{'arcB70':{'npm':'@ai-sdk/openai-compatible',
            'name':'b70 (awaiting hardware)',
            'options':{'apiKey':'dummy','baseURL':'@ARCB70_ENDPOINT@'},
            'models':models}}},indent=2)+'\n')
