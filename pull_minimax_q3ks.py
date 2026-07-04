#!/usr/bin/env python3
"""Pull MiniMax-M2.7 UD-Q3_K_S GGUF via huggingface_hub.
The `hf` CLI is broken on py3.14 (typer/click), and the Xet chunked backend stalls here,
so force the plain, resumable HTTP downloader. Resumes from existing .incomplete files."""
import os
os.environ["HF_HUB_DISABLE_XET"] = "1"          # avoid the stalling Xet backend
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"    # deprecated no-op in this hub version
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "60"     # flaky link — tolerate longer read stalls

from huggingface_hub import snapshot_download

path = snapshot_download(
    "unsloth/MiniMax-M2.7-GGUF",
    allow_patterns=["UD-Q3_K_S/*"],
    max_workers=4,
)
print("DONE:", path)
