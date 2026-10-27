"""Pinned Flash Next CPU/B70 split; estimates require runtime verification."""
import json
import pathlib

GIB = 2**30
MODEL_NAME = "qwen38-flash-q4-256k"
MANIFEST = json.loads(pathlib.Path(__file__).with_name("flash_weights.json").read_text())
MODEL_DIR = "/mnt/xfs/AI_Models/gguf/qwen38-flash/UD-Q4_K_XL"

CPU_WEIGHTS_GIB = 86.3437032699585
GPU_WEIGHTS_GIB = 17.334506511688232
VRAM_GIB = 31.890625
HOST_RESERVE_GIB = 24
RUNTIME_RESERVE_GIB = 4
KV_BYTES_PER_TOKEN = 8640


def estimate(context=262144, slots=3):
    if not (type(context) is int and 4096 < context <= 262144 and context % 256 == 0 and type(slots) is int and slots == 3):
        raise ValueError("context must be an integer > 4096 and <= 262144 and divisible by 256, and slots must be 3")

    attention = slots * context * 6912 / GIB
    indexer = slots * context * 1728 / GIB
    recurrent = slots * 36 * ((4 - 1) * (6144 + 2 * 16 * 128) + 128 * 6144) * 4 / GIB

    return {
        "cpu_weight_gib": CPU_WEIGHTS_GIB,
        "gpu_weight_gib": GPU_WEIGHTS_GIB,
        "attention_cache_gib": attention,
        "indexer_cache_gib": indexer,
        "recurrent_state_gib": recurrent,
        "runtime_reserve_gib": RUNTIME_RESERVE_GIB,
        "vram_budget_gib": VRAM_GIB,
        "host_reserve_gib": HOST_RESERVE_GIB,
        "estimated_vram_with_reserve_gib": (GPU_WEIGHTS_GIB + attention + indexer + recurrent + RUNTIME_RESERVE_GIB),
        "weight_gib": sum(shard["bytes"] for shard in MANIFEST["shards"]) / GIB,
        "cache_device": "GPU"
    }


def model_spec():
    return {
        "context": 262144,
        "slots": 3,
        "reserved": 0,
        "aliases": [],
        "display_name": "Qwen3.8 Flash Next",
        "experimental": True,
        "omit_provisional_label": True,
        "validation": "three-native-256k-slots-and-8k-retrieval-prefix-reuse-verified; full-context-quality-pending",
        "native_context": 262144,
        "shared_pool": "flash-next-q4",
        "memory_estimate": estimate(),
        "weights": {**MANIFEST,
            "filename": MANIFEST["shards"][0]["filename"],
            "bytes": sum(shard["bytes"] for shard in MANIFEST["shards"])
        },
        "args": [
            "-m",
            f"{MODEL_DIR}/{MANIFEST['shards'][0]['filename']}",
            "-ngl", "999",
            "--n-cpu-moe", "40",
            "--no-op-offload",
            "-ot",
            "per_layer_token_embd=CPU",
            "-ctk", "q4_0", "-ctv", "q4_0",
            "--cache-ram", "0", "--ctx-checkpoints", "2",
            "--reasoning-budget", "2048", "--threads", "24",
            "-b", "1024", "-ub", "256",
            "--temp", "1.0", "--top-p", "0.95",
            "--top-k", "20", "--min-p", "0.0", "--fit", "off"
        ]
    }


def pool_spec():
    return {
        "context_tokens": 786432,
        "max_context": 262144,
        "min_context": 262144,
        "slots": 3,
        "reserved": 0,
        "exclusive": True,
        "clear_idle_kv_on_admission": False,
        "preserve_prompt_cache": True,
        "runtime_args": [],
        "kv_bytes_per_token": KV_BYTES_PER_TOKEN
    }
