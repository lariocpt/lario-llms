# Research and delegation provenance

## Scope and confidence

Research date: 2026-10-26. Repository source snapshot HEAD: `873dadc8697db971686e114b639afbf2136f7e75`, plus the pre-existing dirty working tree. Only documentation under this plan directory was intentionally added to the repository during this task. No deployment, GPU smoke probes, backend upgrade or service reconfiguration was performed. Requested local-model research inference ran through the existing gateway; it was not a hardware certification exercise.

Local executable inspection used version output and embedded Go build metadata. It established v233/083e421 and `vcs.modified=false`, but not a byte-for-byte comparison with the published executable. Other owner binaries and effective deployed configurations were not inventoried live. Those are explicit Phase 1 tasks.

Official sources were downloaded to `/tmp/llama-swap-planning/sources/`. Temporary files are a working cache, not durable evidence. Durable references and captured-byte SHA-256 values below allow a future implementer to re-fetch and compare exact inputs; deployment must independently validate artifacts. No upstream source checkout or full raw session transcript is committed into this plan.

## Verified sources

- [swap-v267-config.yaml](https://github.com/mostlygeek/llama-swap/blob/v267/docs/config.example.yaml): Configuration, capture control, groups/capacity semantics. Captured SHA-256 `4a58301c06cf12e67313d4a34fdb4a97d99468d9a5470b1bba0182c8fb813fe8`.
- [swap-load.go](https://github.com/mostlygeek/llama-swap/blob/v267/internal/config/load.go): Legacy groups accepted; old and new routing configuration cannot be mixed. Captured SHA-256 `4e1325e298bad3825b2200ea0c83cb75844e83c9dbcec0a930eba4197d23e377`.
- [swap-server.go](https://github.com/mostlygeek/llama-swap/blob/v267/internal/server/server.go): Private health/running/management route registration. Captured SHA-256 `d5a8e41c2c12913e82522a84ff8f85f248b743b9f7150a17ddadfff9c8f3e582`.
- [swap-v267-release.json](https://github.com/mostlygeek/llama-swap/releases/tag/v267): Release date and exact asset names/digests. Captured SHA-256 `91b7ec8e2854b8920cb649bdd8e56e41e6abef91d0a0bbc4f19f51a28937c5f6`.
- [llamacpp-pinned-readme.md](https://github.com/ggml-org/llama.cpp/blob/caa8191df159f764fb0160e3d2fc6be008948aee/tools/server/README.md): Router API, INI precedence, flags, autoload, count limit and refresh behavior. Captured SHA-256 `009af291f69adaa041be4e79f1550e5f36bcaf3a929373091a7e4ac9b7bbac0c`.
- [llamacpp-pinned-models.cpp](https://github.com/ggml-org/llama.cpp/blob/caa8191df159f764fb0160e3d2fc6be008948aee/tools/server/server-models.cpp): Same-executable child launch, LRU, state and model-scoped dispatch. Captured SHA-256 `e6d25b8d6c26855e75853730c8d86ccd5890dccbfb1f1e1d132b4481d78c37b7`.
- [bifrost-http-release.json](https://github.com/maximhq/bifrost/releases/tag/transports%2Fv2.3.2): OSS HTTP transport release; distinguish enterprise base tag. Captured SHA-256 `990745f41476e32d638092359447db23af0e598da477109c33993fd7ceae5d11`.
- [bifrost-client-release.mdx](https://github.com/maximhq/bifrost/blob/transports/v2.3.2/docs/deployment-guides/config-json/client.mdx): Logging controls, independent connector filters, retention and object-content storage. Captured SHA-256 `9a80a472527a79793350f13b026bab4158de25f5a7e2daebd87e95be8022e361`.
- [bifrost-virtual-keys-release.mdx](https://github.com/maximhq/bifrost/blob/transports/v2.3.2/docs/features/governance/virtual-keys.mdx): Key-specific content policy overrides; virtual-key capabilities require runtime testing. Captured SHA-256 `7b318b7701317f68f9f8a8c9ec2b6fb5135b1541f1e4e600cca231fcfd38fe6a`.

The pinned llama.cpp documentation and implementation were downloaded again using the exact commit URL after resolving master. Mutable master/dev URLs used in preliminary exploration are not the normative references. Bifrost logging findings were rechecked against the HTTP transport release tag, rather than assumed from dev documentation. GitHub release metadata may be amended; asset verification is repeated at execution.

## OpenCode delegation

Requested display model: `gfc rtx-64k 1slt-qw3-VL description Q4 kv8`.

Resolved provider/model: `rtx5080/rtx5080.describe.c65536.kq8_0-vq8_0.s1.capacity.a859cd4ab4`. Configured client context limit observed: 61,440 tokens; output limit: 8,192. Each chunk used a new standalone OpenCode session, without continuing/forking any prior session. Runs used the planning agent and instructions prohibiting implementation, service mutation and credential inspection. The bounded retry supplied verified evidence rather than asking the model to gather a large context.

| Chunk | Fresh session ID | Outcome / treatment |
| --- | --- | --- |
| Current inventory | `ses_e8687ce84ffeec3vNq8AYr84kO` | Draft generated; generic/invented environment and monitoring claims rejected and replaced with direct source inspection |
| Upstream upgrade | `ses_e86870930ffeM4hxsfUs6kjpnp` | Draft extracted from planning tool output; archive filename, routing scope and missing operational detail corrected against official sources |
| Native router | `ses_e86865297ffePj03IyTh5jFhoh` | Repetitive output hit the output limit and included unverified pseudo tool transcripts; research process stopped, unsupported content discarded |
| Initial Bifrost | `ses_e8684574fffeih196NNoX2eQIS` | Owner returned 429 hardware-capacity-exhausted; no usable research result |
| Bounded Bifrost retry | `ses_e8681d80fffeEgPQCV8ZiT768V` | Candidate produced from supplied verified facts; feature checkmarks, unproven claims and invented pilot schedule removed in editorial review |

All implementation-critical claims in the saved plan were reviewed against local source or downloaded official sources. Delegated output is not treated as independent evidence. The final text intentionally omits unsupported release/feature claims, fabricated commands, fake tool transcripts and assertions that proposed integration already works.

The scratch prompts/events/drafts are under `/tmp/llama-swap-planning/`; the fresh sessions can be inspected through OpenCode by their IDs. They are not necessary to implement the saved plan and may disappear with temporary-file cleanup. No other model was substituted for delegated OpenCode inference.

## Revalidation before execution

1. Refresh owner registry/effective deployment and document source/live differences; do not reuse this planning snapshot as proof of production state.
2. Recheck current releases, advisories, exact binaries/images and relevant licenses. Record a new research/deployment pin if versions change.
3. Re-run the contract and hardware acceptance matrices for the selected versions. Unsupported native headroom/preset behavior blocks the affected owner migration.
4. Produce a Bifrost adopt/defer/reject ADR from measured identity, transport, content-policy and logging experiments. Research documentation alone does not establish safe end-to-end support.
