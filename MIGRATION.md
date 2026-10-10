# Native engine migration (in progress)

This branch is an integration candidate. The published Python deployment
remains the qualified rollback reference until every cutover gate below passes.
The native candidate runs on loopback during maintenance; passing compilation
alone does not establish serving qualification.

The native engine starts at Bertholomus's
[`4e80f05`](https://github.com/bertholomus/TensorFold/commit/4e80f05ecba89a4e90d16375ade2eddbdc0a10c4),
with the v0.6.1 recipe and kernel builders at
[`5e90ec9`](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10/tree/5e90ec9302149049e8f019ea035827cb24c206f8).
The rollback source is this fork's `32c4ebea7d0a81808aaa503d88ebe1a84612d0cf`,
documented and published in `29c1a04ecd75ea56ba85502279aa39b0bf6705f8`.
Original checkpoints and prepared rank caches are immutable inputs; generated
native kernels and mutable caches use separate directories.

As of October 10, the integration compiles for GB10. The follow-up source passes
286 Zig CPU/server tests, the native xgrammar contract test, 64 portable recipe
and benchmark contracts, and six native controller contracts. Both ranks' fresh
native cache writers have independent full-byte readback checks. These checks
are separate from serving qualification. The [20-case Python baseline](deployment/release/native-python-baseline-20261010.json)
is recorded separately from native measurements.

The first live candidate reached ready state and exercised text, image input,
prefix reuse and a single-stream drafted/ordinary comparison, then failed at
C4: the router requested an 18-row `_rowmm_parts` variant while the pinned kit
only supplies up to 16. The fix slices wide router rounds into supported
variants. A GPU regression compares every width from 1 through 48 against
independent one-row launches: 9,048,144 words matched, with intact canaries.
The paired monitor stopped both ranks and host restoration passed. A second
live qualification is required; the primitive regression alone does not pass
C32, structured-output, performance or endurance gates.

The second live attempt passed the complete baseline, including C4, and passed
ordinary JSON object/schema and streamed-schema checks. A thinking-budget
schema failed because the forced reasoning close appended a blank-line token
which the schema rejects before its root. A CPU-only probe with the actual
tokenizer and grammar reproduced that rejection. The corrected close ends at
`</think>` for constrained output and lets its mask select the first answer
token; ordinary text retains its existing close. Server and C++ regressions
pass. Both hosts again passed restoration. Remaining feature/capacity gates
still require a new live run.

The third live image, built from `b7b884d`, passed the feature suite: text and
image input; strict JSON/schema/tools including thinking budgets; random and
explicit seeds; all context aliases; Chat, Responses and Messages; and JPEG/WebP
through all three APIs. Greedy and temperature-1 ordinary/drafted output hashes
matched at C4/8/16/24/32, with zero reported cached tokens in those short-prompt
fixtures. Every request received drafts in the drafted runs. Thirty-two distinct
strict schemas and 32 required tool calls also passed with observed C32 decode
overlap. These are short-context checks, not the full 32 × 262k capacity gate.

Thirty-two distinct 16k prefixes passed cold admission, cached replay, extension
and extended replay, including output-hash comparisons and the 64-state bound.
A separate test fragmented live reservations, required real relocation and
compared continued outputs with solo execution after cancellation. Full-context
capacity, matched performance, fault recovery and endurance remain pending.

One parity attempt failed a client assumption: the final SSE response had ended
before the scheduler removed its request. The runtime remained healthy, had no
active GPU stream, and subsequently became idle; all four output hashes already
matched. The failed receipt is retained. The corrected client records a bounded
post-response accounting drain outside its stream timings. Later greedy checks
needed at most about 24 ms. Parity fixtures omit unnecessary LRU eviction for
their fixed 1024-token inputs, which are shorter than a native checkpoint chunk;
they still reject every reported cache hit. Matched performance suites retain
their explicit cold-cache preparation.

Drafting was faster at C4/C8 in those correctness fixtures. At higher concurrency,
its advantage varied with sampling: greedy C16/C24/C32 was slower than ordinary
decoding, while temperature-1 C16/C24 was faster and C32 was close. These are not
matched Python speedups. One tuning candidate is the inherited timing table:
its cost stops increasing beyond 24 rows, even though this profile permits 48.
That is a plausible contributor, not an isolated performance diagnosis. Matched
temperature-1 and deep-context measurements are required before choosing a
production profile.

The serving engine, scheduler and sampler are native. The xgrammar compiler is
a pinned C++ library. Offline compressed-token-map preparation uses the pinned
`tokenizers` package; upstream's bounded Pillow helper handles image codecs
other than the native PNG path. No Python model engine or PyTorch tensor loop
is used for native inference. Fresh rank-cache preparation has a CPU-only native
command; existing rank caches remain read-only and require an independent
comparison of every prepared tensor with the intended Keys checkpoint.
The legacy `prepared_cache_producer` metadata names a known format/loader
revision. It does not establish which commit originally wrote an imported file;
compatibility comes from immutable asset checks and the complete native tensor
comparison.

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
