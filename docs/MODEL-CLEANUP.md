# Model cleanup — 2026-10-05

Only downloads excluded from the current hardware registries and Intel runtime were
removed. A model being unloaded was not enough to make it unused: every selectable
profile, draft model, vision projector and split GGUF shard was retained.

| Host | Deleted paths | Allocated bytes reclaimed | Fresh audit |
|---|---:|---:|---|
| bigcachy | 43 | 361,568,317,440 (361.6 GB) | zero further candidates |
| l-dev-ai / Geekom | 24 | 434,316,271,616 (434.3 GB) | zero further candidates |

Both model partitions were verified as XFS. Before deletion, the audit resolved model
symlinks, protected their blobs, checked retained GGUF headers and split-shard counts,
checked Intel exports, and rejected any unrecognized resident model. Dedicated model
cache directories containing a protected file were retained. Recent large downloads
were excluded from automatic deletion.

bigcachy retains Muse Glimmer and its DFlash draft, Qwen3.8 Q3, Qwen3-VL with its
projector, BGE-M3 FP16, Whisper turbo FP16, Qwen3-8B INT4 and Kokoro INT8. Geekom
retains Qwen3.8 Q8 and Q4 plus all three Flash Next shards. The Geekom registry now
pins the retained Q8/Q4 files directly, so a future model switch does not download
an alternative Hugging Face revision.

Removed downloads include retired MiniMax, Mistral, Qwen3.6, Llama vision, obsolete
OpenVINO exports and redundant model/cache copies. Some retired cache files were
root-owned; only the exact retired directories were removed through Docker. No
general Docker, database or filesystem prune was used.

Full per-path evidence is in `research/cleanup-bigcachy.json` and
`research/cleanup-geekom.json`; fresh audits are the corresponding `*-after.json`
files. `research/cleanup-summary.json` records totals. These are allocated file
bytes, not an assertion that filesystem free space will increase by exactly that
amount under concurrent activity.

Re-audit on the model's owner using:

```sh
python3 scripts/cleanup_unused_models.py --output /tmp/model-cleanup-plan.json
```

Review the plan before adding `--apply`. The script aborts if retained weights or
the XFS mount are missing, or a live model is outside the registry. The inventory
is scoped to dedicated model download locations; project files, datasets, agent
state and databases are outside its deletion scope.
