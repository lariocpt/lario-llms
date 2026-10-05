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
