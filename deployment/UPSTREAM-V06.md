# October 9 upstream review and selective integration

Reviewed on 2026-10-09 (Pacific). The Python branch remains at
[`90b68e0`](https://github.com/bertholomus/TensorFold/commit/90b68e063a0b8bba59aaf13340ef16619e751195),
already covered by our [v0.5.1 integration](UPSTREAM-V051.md). The new engine is
on `deepseek-v41-zig`, reviewed at
[`4e80f05`](https://github.com/bertholomus/TensorFold/commit/4e80f05ecba89a4e90d16375ade2eddbdc0a10c4).
The [recipe](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10/tree/5e90ec9302149049e8f019ea035827cb24c206f8)
is v0.6.1: native Zig serving plus a checked-in kernel kit. This fork continues
to use its existing Python engine with selective ports.

## Decisions, in priority order

| Change | Decision and reason |
|---|---|
| Replay-floor correction, [`bdcfd10`](https://github.com/bertholomus/TensorFold/commit/bdcfd10a2a9091b515e220525d439546ce90de15) | Port now. A replay chunk of at most 16 rows can otherwise attend to stale keys from an earlier request. Use the clipped gathered window and prompt reduction order. |
| Request-order regression coverage | Add poisoned-ring CUDA probes and cold HTTP probes at both sides of the replay boundary. Require complete output-token hashes, zero cache hits and different request orders. |
| Watchdog fault attribution | Add failure stage/type and explicitly aged last-known host samples. Preserve the 2 GiB floor, two-failure policy and immediate cleanup path; do not delay a necessary stop to probe the other host. |
| Matched busy/idle memory observations | Add a finite synthetic test with repeated workloads, normalized retained-prefix occupancy and comparable quiet samples. Record interruptions separately from failures; neither is a pass. |
| Native Zig serving | Defer to a separate migration. Its [`draft.zig`](https://github.com/bertholomus/TensorFold/blob/4e80f05ecba89a4e90d16375ade2eddbdc0a10c4/zig/src/families/dsv41/draft.zig) caps streams at 16, and its model couples the shared pool to context. Preserve our C32, 8,650,752-token shared pool, million-token request limit, Keys, vision, strict outputs and reversible host lifecycle before considering a cutover. |
| Native full-pool queueing, [`ffae47c`](https://github.com/bertholomus/TensorFold/commit/ffae47c3c3b3f4489e19aed106a648e5a9f9a5ca) | Already addressed in this fork by admission queueing and live KV compaction. Keep our implementation and its capacity/parity tests. |
| AOT fallback, Pillow-child recovery and kit builders | Revisit with a Zig port. These serve the native kit/subprocess architecture; the current JIT/in-process image path has different requirements. Do not import binary kits into the current image. |
| Earlier ring-zeroing experiment | Skip. The replay-floor change supersedes it; zero keys still contribute attention weight. |
| Smaller reserves, blanket arena tuning or smaller grammar caches | Defer until measurements attribute retained memory. Do not trade away the watchdog or structured-output support on speculation. |

Bertholomus reports improved deep-context decode and sustained C4 throughput for
the native engine. Those results use their configuration and assets; they do
not establish C32 performance or memory headroom for this deployment. No new
speed claim follows from this selective correctness port.

## Replay correction

`TF_DS_REPLAY_FLOOR=1` is the engine and recipe default. At a shortened replay
boundary, it gathers only valid keys at or above the replay floor and uses the
prompt path's single-split reduction/index padding. Ordinary decode and prompt
chunks that do not cross this boundary retain their existing paths.

With the recipe's 1,024-token chunks, test lengths include `1024*k + 112..127`
and short final chunks, as well as neighboring controls. CUDA regressions also
cover the upstream 2,048-token chunk geometry. Corrected replies may differ
from previous releases for affected prompts. Random unseeded sampling remains
the deployment default; regression requests explicitly select deterministic
sampling. `TF_DS_REPLAY_FLOOR=0` is available for controlled comparison and
restores the known defect; it is not a recommended serving configuration.

## What the memory investigation establishes

The stopped 78-minute run on October 9 passed finite functional/capacity checks,
including two warm C32 waves with identical full output hashes and a compaction
of 8,189,952 rows. Sampled host availability stayed above 2.647 GiB on the head
and 3.233 GiB on the worker. There were no GPU allocation errors; one health
timeout recovered. Native heap trimming released some free pages, but live
allocations also grew between startup and the busy endpoint. Those states were
not comparable, so that growth does not establish a leak.

The user stopped the run after approximately 78 minutes. It is **not a 24-hour
stability pass**, and its planned quiet intervals were not completed. The
original 22-hour worker memory-floor failure still lacks enough evidence for
a definitive allocation-level cause. See [memory diagnostics](MEMORY.md).

## Integration gates and rollback

The selected changes require offline regressions, poisoned-ring GPU tests on
both hosts, cold replay-boundary probes, text/vision/strict-output/sampling
checks, C32 and native-million capacity, finite matched quiet observations,
and normal stop/restoration/restart. Results must name the exact source/image
and preserve failed attempts. Endurance and deep-context speed graphs remain
separate work; the stopped endurance test is not automatically resumed.

Use the [pinned deployment workflow](WORKFLOW.md) and [rollback instructions](ROLLBACK.md).
Preserve the previous source/image selectors and the current installation's
private ownership records and host journals. Stop and verify restoration before
selecting the previous clean checkout and matching image; never restore old
ownership journals over live state. No reboot or persistent host setting is
required for these code changes. Hardware validation is recorded separately
from this review's decisions.
