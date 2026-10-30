"""Translate Halogen's aggregate native occupancy for the owner gateway."""


def slot_snapshot(health, slots):
    if (health.get('capability_probe') != 'ok' or health.get('status') != 'ok'
            or health.get('engine', {}).get('responds') is not True
            or health.get('context') != 262144 or health.get('slots') != slots
            or health.get('kv_pool_positions') != 524288):
        raise ValueError('Halogen capability probe is not ready')
    n = health.get('in_flight')
    if type(n) is not int or not 0 <= n <= slots:
        raise ValueError('Halogen occupancy unavailable')
    # The engine exposes a count, not slot identities. The owner needs the count
    # and confirmed zero occupancy to unload; these ids carry no routing meaning.
    return [{'id': i, 'n_ctx': 262144, 'is_processing': i < n} for i in range(slots)]
