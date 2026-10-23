"""Keep a fixed OpenVINO workload on its registered GPU across enumeration changes."""


def bind_gpu(requested, expected_uuid, core=None):
    if not requested.startswith('GPU') or not expected_uuid:
        return requested
    if core is None:
        import openvino as ov
        core=ov.Core()
    normalize=lambda value: str(value).replace('-','').lower()
    matches=[d for d in core.available_devices if d.startswith('GPU')
             and normalize(core.get_property(d,'DEVICE_UUID'))==normalize(expected_uuid)]
    if len(matches)!=1:
        raise RuntimeError('registered OpenVINO GPU is absent or ambiguous; fallback refused')
    return matches[0]
