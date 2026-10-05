# Current serving gotchas

1. OpenCode v2 can stall while indexing a huge home tree. The accidental `/home/lario/.git` repository was removed on 2026-10-05 after narrowing its untracked directories stopped a ~57-second service replacement loop. See [diagnosis](docs/OPENCODE.md).
2. Model selection restarts the hardware backend, not OpenCode. A concrete API model request may swap profiles; the hardware alias returns to the selector's chosen profile.
3. Keep all caches on the owner's XFS mount. `-hf` uses llama.cpp's cache as well as Hugging Face tooling's separate cache.
4. ROCm serving uses `/app/llama-server`, the Radeon render node, `/dev/kfd`, and `/usr/share/libdrm`. Do not spoof gfx1100 with HSA_OVERRIDE_GFX_VERSION.
5. DFlash draft KV stays f16; target KV is q8_0. DFlash changes sampling and trades one slot for decode speed. A long concurrent prefill can starve another slot's decoding.
6. RTX Qwen3.8 puts KV in host RAM (`--no-kv-offload`) to retain maximum context. It is text-only. Vision profiles use a projector and bound encoder batches; test large images, not only 1-pixel probes.
7. Container liveness does not prove generation. RTX monitoring checks native serving and periodically infers with the current concrete profile, without switching hardware modes.
8. Keep `--cache-ram 0`: older llama.cpp host prompt-cache paths aborted during compaction. In-slot prefix reuse is separate.
9. GenAI 2026.4.0.0 requires matching OpenVINO Runtime 2026.4.0 and tokenizers 2026.4.0.0. Runtime 2026.4.1 did not supply the required libopenvino.so.2640 ABI in the tested environment.
10. NPU visibility is not compilation proof. The installed intel-npu-compiler fixes compilation; Whisper succeeds, but the tested Qwen3 INT4 export fails NPU compilation. BGE-M3 NPU requires static padding and a shorter input than the RAG contract; use CPU.
11. Chroma persistence must mount `/data` with the current server image. Supplying documents without explicit embeddings can create a 384-dimensional collection; both ingest paths now supply BGE-M3 vectors.
12. Kokoro requires a voice embedding tensor, and espeak-ng for multilingual phonemization and English dictionary fallback. A nonempty waveform plus transcription is stronger validation than successful compilation.

Previous incident records: [historical gotchas](docs/history/GOTCHAS-before-2026-10-05.md).
