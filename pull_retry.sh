#!/usr/bin/env bash
# Flaky-link-proof wrapper: keep resuming the HF download until all shards land.
# huggingface_hub resumes each run from the existing .incomplete file, so peer-closed
# crashes just cost a retry, not progress.
cd /mnt/Shared/personal/lario-llms
for attempt in $(seq 1 100); do
  echo "===== [attempt $attempt] $(date +%T) ====="
  if python3.14 -u pull_minimax_q3ks.py; then
    echo "===== DOWNLOAD COMPLETE (attempt $attempt) ====="
    exit 0
  fi
  echo "----- exited non-zero; resuming in 10s -----"
  sleep 10
done
echo "gave up after 100 attempts"; exit 1
