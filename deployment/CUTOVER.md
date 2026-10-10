# Portable cutover qualification

This records the initial portable cutover. The subsequent
[FP32 correctness update](UPSTREAM-V051.md) changes three engine files and has
separate qualification and measurements; the results below remain historical.

The 2026-10-08 UTC cutover uses a clean, separate deployment checkout of
`2f65892284376d6a59eda1270e3a9ab59f79897b`. Its locally built image ID is
`sha256:07cd312dca050f9be3c14c5ca9c3ec728c3a28d1b9c2142e45c6a4d1fe54f98b`.
This identifies the tested local image; it is not a published registry image.

**The cutover passed.** Inference, capacity, retention, benchmark, paired cleanup,
host restoration and preserved-server fallback checks completed. The new pair
was restarted at the selected source/image and passed its final feature, LAN
access and monitor checks.

## Scope and source identity

This is a migration using fully verified existing model assets and completed
prepared-weight caches. It qualifies that reuse path and a fresh portable image
build. Fresh Hugging Face download/extraction remains a separate hardware gate.

The 476 pinned engine/client files match the previously qualified engine. All
225 dependency-inventory lines match the previous image, and the installed
runtime files match the selected source. The image uses the pinned NVIDIA base
in the [Dockerfile](config/Dockerfile); the inventory is not a hermetic package lock.

The controller fixes ownership-label filtering and discovers the DRM device
after reloading the module. Verified reuse shares immutable model bytes and
completed prepared caches, with read-only serving mounts and independent mutable
kernel caches. New ownership records and display journals belong to the new
installation. Previous source, images, assets and recovery records are retained.

An initial prepared-cache import was interrupted after the model view completed.
The available evidence pointed to protected root-owned hardlinks; the original
error stderr was not retained. Scoped protected-link handling and cache-only
resume were added. The resumed import and full verification passed while
preserving source bytes, ownership and permissions.

The selected profile adds a 109 GiB allocator upper bound per rank; the startup
host floor can lower it further. The KV pool, context limit and concurrency stay
at 8,650,752 logical tokens, 1,048,576 tokens per request and 32 active slots.
The paired watchdog retains its 2 GiB available-memory threshold.

## Completed inference checks

The [sanitized acceptance receipt](../release/cutover-acceptance.json) records
parameters, timing, counter checks and hashes of the private source receipts.
All inputs come from the published synthetic clients; ordinary inference
traffic was not used.

| Check | Observation |
|---|---|
| Text, vision, JSON/schema/tools and streaming | Passed together with Keys enabled |
| Sampling | Random defaults, explicit seeds and returned-seed replay passed |
| Ordinary/default comparison | All 104 paired replies matched; 208 inference requests at C16, C24 and C32 |
| Large sessions | Two waves of 32 × (261,120 input + 1,024 reply tokens); all 32 decoders observed |
| Populated pool | Sampled 8,388,288 logical tokens across independent session states |
| Native-million retrieval | 1,048,320 input + 256 forced reply tokens, zero cached input, all three passphrases recovered in 890.5 seconds |
| Small concurrent requests | Arithmetic and JSON completed in 3.383 and 3.534 seconds during the million-context test |
| Admission | Eight million-token reservations; ninth waited and resumed; nine offset-output comparisons matched solo replies |
| Cancellation/recovery | Plain and constrained cancellation, oversize rejection and healthy follow-up passed |
| Mixed soak | Nine waves, 288 text/vision/JSON requests and a structured-output recheck |
| Prefix retention | 132 requests; 32 entries, two recent checkpoints, sequential reuse/extensions and least-recently-used eviction passed |

The main acceptance suite took 3,014.8 seconds. Retention took another 484.3
seconds and held 228 MiB of checkpoint tensors per rank. Allocation OOM and retry
counters stayed zero; all 96 captured graphs remained sealed.

The parent observer missed three of 1,424 health reads during one C32 parity
wave; that child missed two observations. Retention had no gaps in 88 samples.
The lowest parent memory observations were **2.16 GiB on the head / 3.45 GiB on
the worker**. The head's margin above the watchdog floor is limited. These are
finite test results, not an uptime or available-memory guarantee.

The 32 large sessions use an identical primed document. They establish populated
independent session capacity, not cold ingestion of 32 different documents.
Active and retained sessions share the pool. A single three-needle retrieval
probe is not a broad million-context quality evaluation, and overlay identity
and functioning do not quantify abliteration effectiveness.

## Benchmarks and recovery

All 20 local cases passed: 178 scored requests and 46,336 output tokens. Every
token and text hash matched the previous deployment with the same inputs and
budgets. The unchanged upstream client also passed its C1 and cold 32K/128K
checks, including zero cached prefill tokens and exact counters. Current C1
code/prose/counting medians are 93.9 / 58.2 / 136.7 output tok/s with that client;
local C16/C32 steady decode is 214.5 / 266.9 aggregate tok/s. The
[matched tables and ranges](../benchmarks/README.md#portable-cutover-measurements)
also retain the slower whole-cold-wave results.

| Lifecycle check | Observation |
|---|---|
| Interrupted controller | Both display journals survived an injected exit; normal stop restored both hosts in 10.3 seconds |
| Idle worker loss | The paired monitor stopped/removed both ranks and restored both hosts; test completed in 51.5 seconds |
| Broader host comparison | Packages, persistent configuration hashes, services, driver/kernel, groups, Docker runtime configuration, display state and physical networking matched the saved baseline; no GPU compute processes remained |
| Preserved-server fallback | Previous source/image/assets started and passed text, vision and structured-output checks; its own controller then stopped it and both hosts again matched the baseline |
| Final selected restart | Pinned portable source/image started in 87.0 seconds; text, vision, strict output, random sampling/replay, LAN access and the paired monitor passed |

The [sanitized lifecycle receipt](../release/cutover-lifecycle.json) records these
checks and the initial setup correction. Shared model/prepared mounts were
read-only on both final ranks. The final idle observations were 3.66 GiB
available on the head and 3.18 GiB on the worker. These are separate observations
from the earlier stress-test minima above.

The tests restored idle hosts before the final serving restart. Serving reapplies
the journaled current-boot display settings. No host reboot, host package install
or persistent network/display configuration edit was performed by this cutover.
New source, images, owned data paths, compiled caches and evidence remain on disk;
the [rollback runbook](ROLLBACK.md) distinguishes host restoration from optional
artifact removal.

## Operations and remaining release work

Keep development in the canonical repository and serving in a clean checkout
pinned to the selected source/image pair. Preserve its ignored configuration,
ownership records and journals. The [workflow](WORKFLOW.md) and
[rollback runbook](ROLLBACK.md) distinguish restoring idle hosts from optionally
starting an older server.

The [release status](../release/STATUS.md) tracks fresh acquisition, licensing and
other remaining release gates. The historical measurements remain labeled in
the [benchmark methods](../benchmarks/README.md).
