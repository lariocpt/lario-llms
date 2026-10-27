# Strata Guidance for B70 Flash Next

This document provides verified guidance for using Strata with the B70 Flash Next model. All information is derived from upstream revision `4b9e05a2a806a3fe24f7b2560d98626c37dade35` and cross-referenced with related documentation.

## Strata and B70 Support

Strata has its own SYCL engine and official B70 support. It is not a set of LLaMA server flags.

## Q4 Guide

The Q4 guide matches our `arcB70/flash_weights.json` exactly, despite different Hugging Face revisions.

## Intel Guidance

Intel guidance emphasizes:

- `--stream-experts`
- `--expert-cache auto`
- Host mirror/PLE handling
- `--prefill 8192` with `--prefill-borrow` for large context (Battlemage 24GiB+)
- `--kv-resident 32768`
- Reserve 2048MiB above 32k as starting guidance
- AOT `bmg-g31`
- Persistent JIT cache off
- `STRATA_VERIFY_NO_HOST=1` required for Xe partial experts and `STRATA_VERIFY_DEVICE_PLAN=1`

These are Strata flags, not drop-in LLaMA.cpp flags.

## Q4 KV in Strata

Q4 KV in Strata may use Hadamard rotation and does not assure identical numerics/memory to plain LLaMA Q4_0.

## Intel Benchmarks

Intel benchmarks cited use IQ1/IQ3, not our Q4. Speed cannot be promised.

## Batching

Generic batching docs describe parallel N/batch N, but Intel UD Q4 + Q4 KV + 3x262144 concurrency is unverified.

## Validation

- Preserve prompt/prefix cache fields and current behavior
- Never recommend blanket `cache_prompt=False` or forced KV erase as a fix

## Controlled Isolated Tests

Conduct A/B tests between unified pool vs explicit per-sequence context with the same weights, cache precision, total tokens, prompt prefix reuse:

- Measure prefill and decode (1/2/3), short decode beside long prefill
- Retained KV span, CPU/GPU waits, memory, thermals
- Progression when one ends

## Live Changes

No live changes until user pauses remaining work and owner/native idle is verified.

## Recent Observations

- One active B70 request
- Idle cancelled slot 155k tokens
- Other idle 41k
- Remaining 225k

These observations are consistent with retained-span interference; a controlled comparison is still required.

## Gateway

Currently forces `cache_prompt=False` for all shared pools (Arc and Geekom). This was observed and not approved as future policy.

## Flash Q4 Weights

Flash Q4 weights downloaded and SHA verified; activation pending.

## Next Tests

Verify exact Q4 format support and Intel concurrency before a one-session smoke,
then compare two and three sessions. Do not replace the engine automatically.

---

## References

- [Intel Arc](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/docs/INTEL_ARC.md)
- [Intel engine](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/docs/INTEL.md)
- [Unsloth Q4](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/docs/UNSLOTH_Q4.md)
- [Batching](https://github.com/Niko1221/Strata/blob/4b9e05a2a806a3fe24f7b2560d98626c37dade35/docs/BATCHING.md)

---

*This document is for diagnostic purposes only and does not constitute official recommendations.*
