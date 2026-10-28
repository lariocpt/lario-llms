# Tool image recovery

Confirmed incident: session `ses_e8aaaf1afffeo2g24Pn4tbP1vT` failed at
2026-10-28T01:25:57Z immediately after `read` returned screenshot file parts.
The Arc B70 shared pool correctly rejected image content. The existing prompt
attachment hook only covers user attachments, leaving tool-returned images and
persisted image history uncovered.

The fixed-model plugin now converts inline image_url parts at the HTTP request
boundary through the existing authenticated vision bridge. This includes old
history without rewriting the session database. Text, roles, tool identifiers,
and identity headers are preserved. Image descriptions use the existing disk
cache, so retries and subsequent requests reuse evidence. Remote URLs remain
rejected. A vision failure leaves the original request/history intact and fails
before sending unsupported pixels to the text pool.

Validation: all nine attachment and run unit tests pass. The isolated test
`python3 tests/check_opencode_attachments.py` passes against the installed
OpenCode executable with fake HTTP owners for three paths: user attachment,
actual read-tool image followed by agent continuation, and a subsequent turn
reusing the cached image description. Installed plugin source was updated and
`opencode reload` completed successfully on 2026-10-28. The affected session
was resumed through the prompt API. Its screenshot was successfully analysed
by the live RTX 3060 Ti fixed describe profile and cached as visual evidence.
Session history was preserved.

Limit: outbound conversion currently covers OpenAI-compatible image_url content
parts used by these providers. Other multimodal formats remain rejected by the
pool. Vision evidence is an interpretation; the coding model does not see pixels.
