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
        if hardware=='arcB70' and prepare(hardware).get('enabled_models'):
            entry['status']='partially-active'
            entry['live_hardware_id']='arcB70'
        entry['profiles'] = ([public(model) for model in profiles(prepare(hardware)).values()]
                             if p['source_registry'] else [])
        if hardware=='arcB70':
            enabled=set(prepare(hardware).get('enabled_models',[]))
            entry['profiles']=[profile for profile in entry['profiles'] if profile['model'] not in enabled]
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
        'disabled_providers':[] if prepare('arcB70').get('enabled_models') else ['arcB70'],
        'provider':{'arcB70':{'npm':'@ai-sdk/openai-compatible',
            'name':'b70' if prepare('arcB70').get('enabled_models') else 'b70 (awaiting hardware)',
            'options':{'apiKey':'dummy','baseURL':'@ARCB70_ENDPOINT@'},
            'models':models, **({'whitelist':[p['id'] for p in entries.values() if p['model'] in prepare('arcB70')['enabled_models']]} if prepare('arcB70').get('enabled_models') else {})}}},indent=2)+'\n')
