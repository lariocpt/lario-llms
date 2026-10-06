# OpenCode configuration and the home-repository stall

Verified on bigcachy, 2026-10-05, OpenCode 2.0.22. Loaded settings come from
`~/.config/opencode/opencode.json`, rendered from machine-setup. Default `geekom/geekom`;
Radeon `7900xt/7900xt`; RTX text alias `rtx5080/rtx5080`, image profiles `rtx5080/ocr` and
`rtx5080/describe`. Native Intel services are not chat providers. Explicit modalities stop
OpenCode assuming every unspecified model accepts images. Legacy `attachment` flags are
omitted because v2 reports them unsupported.

Real OpenCode CLI verification passed: default Geekom returned OPENCODE_OK, then read a hidden
random token from a disposable file and wrote the correct token through read/write tools.
The Radeon returned AMD_OPENCODE_OK and used a real read tool. RTX returned RTX_OPENCODE_OK;
its OCR profile read an attached image's invoice 73142 and total 286.75 correctly.

After those request tests, a persistent UI restart issue was investigated separately.
Logs showed `Event stream stalled`, health checks timed out, and clients replaced the service
roughly every 57 seconds. The server consumed ~100% of a CPU core and ~2.3 GB RSS while idle;
RTX stayed running and completed requests. A UI was rooted at `/home/lario`, with a home Git
repository created the previous day for RTX scripts. Adding a local exclusion for untracked
home directories stopped the stall; health checks then took 1–7 ms and 15-second heartbeats
arrived normally with a stable PID. At the user's request `/home/lario/.git` was subsequently
deleted, preserving home files and all project repositories. Another 70-second observation
confirmed stable health and heartbeats after removal. The model selector scripts contain no
OpenCode restart/reload commands.

The observations establish home-tree indexing as the operational trigger; the precise hot
function inside the compiled OpenCode binary was not profiled. Request success alone had not
proved the persistent UI was healthy. The fix was verified with both.

Source: host OpenCode logs and direct HTTP/process observations, plus the official
[client watchdog](https://github.com/anomalyco/opencode/blob/v2.0.22/packages/client/src/solid/connection.ts),
[service recovery](https://github.com/anomalyco/opencode/blob/v2.0.22/packages/client/src/effect/service.ts),
and [file search](https://github.com/anomalyco/opencode/blob/v2.0.22/packages/core/src/filesystem/search.ts).

## Active alias inspection and model switching

The `lario_models` MCP adds `model_status` and `model_options`; bigcachy/l-dev-ai
also enable guarded `model_switch` through existing owner SSH access. Media and
mini-mobile remain status-only. The tools distinguish the saved alias target
from actual residency, expose per-slot context and preserve held/busy/health/
rollback checks. They do not restart OpenCode or export administration keys.
See [the MCP contract](../shared/model_tools/README.md).

OpenCode's custom-provider `models.<id>.name` supplies the displayed picker label.
The alias ID remains stable when its owner changes model/context. A static label
does not track `/running` automatically; use MCP live status. A future private
label refresh can use the supported idle reload, while preserving offline/stale
distinctions. [Custom-provider display names](https://docs.opencode.ai/docs/providers/).

The real OpenCode v2 model-MCP smoke passed on October 6: completed
model_options and model_status calls, structured six-slot Flash listing and
ready RTX residency, no switch, unchanged background PID (163.041 seconds).
All four client sources explicitly set codemode=true. A partial legacy MCP
override is rejected during normalization; a connected server alone is not
tool-execution proof. The source-backed smoke uses a full read-only definition
and checks nested call metadata and returned JSON. Initial failures are retained.
Geekom OpenCode 1.18.5 lists both Intel and model MCPs connected; media has no
OpenCode executable, so only real stdio MCP checks are claimed there.
