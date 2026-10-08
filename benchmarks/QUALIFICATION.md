# Historical engine qualification

These are summaries of the original installation's completed acceptance work, not results from the portable lifecycle in this repository. The engine files match [the qualified source](../release/engine-source.json). The original raw host journals and operational receipts are private and are not bundled; a public release needs fresh portable-install receipts with the same relevant gates.

| Gate | Historical observation |
|---|---|
| Text, vision and strict output | Passed together with Keys; JSON/schema/tool constraints use ordinary decoding |
| Sampling | Random, prompt-derived and explicit seed behavior checked |
| Ordinary/drafted control | 104 paired replies; 208 inference requests completed; two health polls timed out |
| Large sessions | Two C32 waves, 261,120 input + 1,024 output per stream, identical primed document; all 32 decoders observed |
| Populated pool | Sampled 8,388,416 logical tokens and 8,454,144 reserved rows |
| Native-million retrieval | 1,048,320 input + 256 reply budget, zero prefix hits, all three passphrases recovered; 902.7 seconds |
| Coexisting small requests | Arithmetic/JSON requests completed in 0.855 / 1.612 seconds during the million-context gate |
| Admission and cancellation | Eight million-token reservations; ninth held and resumed; nine offset-output checks matched solo references; cancellation and oversize rejection passed |
| Mixed soak | Nine waves, 288 mixed requests, plus a structured-output recheck |
| Prefix retention | 132 requests, 32 entries, two recent checkpoints, 228 MiB idle checkpoint tensors per rank, no allocator/capture growth |
| Paired failure recovery | Idle worker deliberately killed; both ranks cleaned up in 48.703 seconds; stopped hosts matched their baseline |
| Final selected start | Image/capacity, text, vision, JSON and prepared-cache checks passed |

The combined qualification took 3,010.9 seconds. The parent missed three of 1,429 health observations; the retention test missed one. The full-session child sampled a minimum 2.35 GiB head availability, above the 2 GiB host floor but with limited margin. Allocation OOM/retry counters stayed zero and 96 graphs remained sealed. These observations describe a finite test run, not an uptime or memory guarantee.

The Keys overlay was checked for tensor identity, coverage, precedence and combined functioning. These tests do not quantify abliteration effectiveness or guarantee unchanged reasoning/vision quality. Likewise, successful three-needle retrieval is not a comprehensive million-context quality evaluation.

The new installation needs to reproduce acquisition, build, paired launch and restoration as well as these inference gates. Its offline tests exercise ownership, failure paths and command construction; they cannot establish GPU correctness, resource fit or actual host recovery.
