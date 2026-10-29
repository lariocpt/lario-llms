"""Validated owner geometries and native context-extension arguments."""
NATIVE_CONTEXT = 262144
MODES = {(1048576, 4): (262144, 4), (1048576, 2): (524288, 2)}


def owner_geometry(total_context, slots):
    try:
        return MODES[(total_context, slots)]
    except KeyError:
        raise ValueError('owner must request four 256K or two 512K contexts') from None


def context_args(context):
    if not 4096 <= context <= 524288 or context % 256:
        raise ValueError('context must be a multiple of 256 between 4096 and 524288')
    args = ['--max-context', str(context)]
    if context > NATIVE_CONTEXT:
        args += ['--rope-scaling', 'yarn', '--rope-scale', str(context / NATIVE_CONTEXT),
                 '--yarn-orig-ctx', str(NATIVE_CONTEXT)]
    return args
