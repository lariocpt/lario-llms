# XFS Migration & Optimization Plan for AI Models

This document outlines the planned upgrade path for moving AI LLM weights (GGUF, Safetensors) from the current Btrfs partition to a dedicated, highly optimized XFS partition.

## Why XFS over Btrfs?
Btrfs uses Copy-On-Write (CoW), which guarantees data integrity but massively fragments large, multi-gigabyte monolithic files like LLM weights. XFS handles massive sequential files effortlessly without fragmentation, allowing the NVMe drive to stream the weights directly into GPU VRAM at maximum hardware speed.

## The Migration Steps

### 1. Partition Shrink (GParted Live USB)
- Boot into a Fedora or Ubuntu Live USB.
- Target `/dev/nvme0n1p7` (the `Shared` Btrfs partition).
- Shrink the partition by ~300GB by pulling the **RIGHT boundary inwards** (Free space following). *Never move the starting sectors.*

### 2. XFS Creation
- Select the newly created 300GB unallocated space.
- Format as **XFS**.
- Label the partition: `AI_Models`.

### 3. FSTAB Mount Optimizations (Crucial)
Once booted back into Fedora, we will mount the new partition using specific flags optimized for AI workloads.

Add this entry to `/etc/fstab`:
```text
LABEL=AI_Models   /mnt/AI_Models   xfs   defaults,noatime,inode64   0 2
```

**Optimization Breakdown:**
- `noatime`: Disables access timestamp updates. When `llama.cpp` streams millions of chunks, updating metadata for every read wastes massive I/O cycles. `noatime` entirely prevents this.
- `inode64`: Highly recommended for multi-terabyte XFS filesystems. It allows inodes to be mapped into 64-bit address space, preventing inode clustering bottlenecks.

### 4. Docker Re-Targeting
Once mounted, update `docker-compose.override.yml` so the `llamacpp` container points to the new XFS mount:
```yaml
services:
  llamacpp:
    volumes:
      - /mnt/AI_Models:/models
```
