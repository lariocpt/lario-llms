# Geekom admission recovery — 2026-10-21

Bigcachy OpenCode sessions received `backend_reconciling` despite Geekom
having free inference slots. The regular Qwen3.8 Smart profile was healthy:
245,760 tokens per slot, five slots, and Q8 key/value cache. Inspection found
three processing slots and two idle slots.

An interrupted upstream stream marked the gateway's accounting uncertain.
The subsequent admission check refused every request until all other tracked
requests finished, including healthy requests for the same resident profile.
The status endpoint also concealed that internal uncertainty flag.

The correction reconciles real native backend slots while requests are active.
Successful inspection permits the same fixed profile when capacity remains.
Different-profile activation still requires idle hardware; unknown occupancy
still refuses admission. Actual backend occupancy contributes to reported
capacity, including work not tracked after a gateway restart. Cancellation
identity also requires an explicit run header rather than treating a whole
OpenCode conversation as one permanently cancelled run.

Only `lario-admission@geekom.service` was restarted. The model backend was
not restarted or swapped. Existing OpenCode callers automatically reconnected.

Validation uses focused gateway tests, including interrupted-stream admission
alongside healthy work, untracked occupancy, unavailable monitoring, and real
native slot inspection. This incident check is not a performance benchmark.
