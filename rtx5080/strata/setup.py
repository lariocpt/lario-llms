from pathlib import Path
APP = Path.home() / 'strata'
SOURCE = APP / 'terminal/0.1.54'
ENGINE = APP / 'components/engine/0.1.54-linux-x86_64-cuda-cuda13'
MODEL = Path('/mnt/xfs/AI_Models/strata/models/qwen38-flash-next-nvfp4-gptq')
PACK = MODEL / 'pack'
SHARDS = [MODEL / 'qwen-nvfp4-gptq-dense.gguf', MODEL / 'ple-fp8.gguf']
