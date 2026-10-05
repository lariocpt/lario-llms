# Current hardware/model choices

The hardware-owned registries are the source of truth: [Geekom](geekom/README.md), [RX 7900 XT](7900xt/README.md), [RTX 5080](rtx5080/README.md), and [Intel workloads](intel/README.md).

Geekom smart uses Q8 for quality; medium uses Q4 to reduce weight memory. Each has larger-window/fewer-slot and smaller-window/more-slot profiles. Flash Next is now functional. Muse DFlash trades one concurrent slot for faster speculative decoding; plain Muse offers three slots. Discrete-card Qwen3.8 uses Q3 weights and CPU KV cache for a full 262144-token allocation, with a throughput cost as context grows. RTX OCR/comparison and description use the same Qwen3-VL weights with different context/image budgets; choosing the best vision weights across all contenders remains a quality benchmark rather than a proven universal ranking.

Intel device placement follows the CPU/iGPU/NPU measurements in intel/research. BGE-M3 compatibility is required for existing RAG vectors. Historical model descriptions are in docs/history/model_strengths_weaknesses-before-2026-10-05.md and are excluded from current KB ingestion.
