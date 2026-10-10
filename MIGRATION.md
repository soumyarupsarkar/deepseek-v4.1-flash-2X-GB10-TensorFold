# Native engine migration (in progress)

This branch is an unqualified integration candidate. The published Python
deployment remains the production and rollback reference until every cutover
gate below passes. A successful compilation is not a serving qualification.

The native engine starts at Bertholomus's
[`4e80f05`](https://github.com/bertholomus/TensorFold/commit/4e80f05ecba89a4e90d16375ade2eddbdc0a10c4),
with the v0.6.1 recipe and kernel builders at
[`5e90ec9`](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10/tree/5e90ec9302149049e8f019ea035827cb24c206f8).
The rollback source is this fork's `32c4ebea7d0a81808aaa503d88ebe1a84612d0cf`,
documented and published in `29c1a04ecd75ea56ba85502279aa39b0bf6705f8`.
Original checkpoints and prepared rank caches are immutable inputs; generated
native kernels and mutable caches use separate directories.

As of October 10, the integration compiles for GB10 and has passed 284 Zig CPU
tests plus the native xgrammar contract tests. The portable controller's native
health and launch contracts also pass. These results precede hardware serving
qualification. The [20-case Python baseline](deployment/release/native-python-baseline-20261010.json)
is recorded separately from any future native measurements.

The serving engine, scheduler and sampler are native. The xgrammar compiler is
a pinned C++ library. Offline compressed-token-map preparation uses the pinned
`tokenizers` package; upstream's bounded Pillow helper handles image codecs
other than the native PNG path. No Python model engine or PyTorch tensor loop
is used for native inference. Fresh rank-cache preparation has a CPU-only native
command; existing rank caches remain read-only and require an independent
comparison of every prepared tensor with the intended Keys checkpoint.

## Required gates

1. Pinned, reproducible native builds, host tests and rank-cache compatibility.
2. Keys overlay provenance, text and vision; strict JSON/schema/tool output;
   random unseeded sampling, explicit seeds and configurable prompt-derived
   seeds; the existing context aliases and request limits.
3. C32 with an 8,650,752-token shared KV pool, independently sized million-token
   requests, bounded retained prefixes, admission queueing and live compaction.
4. Reversible DRM allocation and host settings, honest memory/health counters,
   peer failure handling and restoration through the deployment controller.
5. Matched synthetic throughput, latency, correctness and memory measurements
   against the Python reference, including deep context and concurrency.
6. A new bounded 24-hour synthetic qualification with comparable quiet windows,
   cancellation and recovery tests. Preserve failed/interrupted receipts. The
   previously user-stopped endurance process must remain stopped.
7. Reviewed source, attribution, setup/rollback documentation and sanitized
   evidence. Cut over only after feature, capacity and stability parity plus
   a measured benefit; otherwise restore the qualified Python deployment.

## Gaps found in the upstream baseline

- The native adapter couples pool size to the per-request context limit.
  RoPE tables and scratch allocations also use that combined value.
- Stream arrays permit at most 16 slots. A larger slot count must also respect
  verifier, drafter, MoE, graph and communication buffer limits.
- Native HTTP validation knows structured formats, but the CUDA engine does
  not advertise or enforce strict outputs or required tool calls.
- Compressed KV extents use ordinary CUDA allocation; our DRM-backed pool and
  reversible host lifecycle need a native implementation.
- Retained extents can be evicted, but there is no live compaction path.

These are implementation requirements, not settings that can safely be enabled
without further work. Upstream's published C4 speeds do not establish this
branch's Keys/C32 performance.

## Rollback contract

Preserve the qualified checkout, images on both hosts, verified model assets,
installation ownership and host journals. Stop the candidate through its own
controller and verify host restoration before starting the qualified checkout
with its matching image. Never replace current ownership journals with old
copies. Candidate builds and CPU-only tests do not change the serving selector.
Keep private host configuration, operational logs, credentials and raw receipts
outside Git; publish only synthetic fixtures and reviewed aggregate evidence.
