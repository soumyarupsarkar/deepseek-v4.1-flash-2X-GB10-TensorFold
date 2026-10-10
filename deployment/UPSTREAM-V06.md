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
| Replay-floor correction, [`bdcfd10`](https://github.com/bertholomus/TensorFold/commit/bdcfd10a2a9091b515e220525d439546ce90de15) | Ported. A replay chunk of at most 16 rows could otherwise attend to stale keys from an earlier request. The correction uses the clipped gathered window and prompt reduction order. |
| Request-order regression coverage | Added poisoned-ring CUDA probes and cold HTTP probes at both sides of the replay boundary. They require complete output-token hashes, zero cache hits and different request orders. |
| Watchdog fault attribution | Added failure stage/type and explicitly aged last-known host samples. The 2 GiB floor, two-failure policy and immediate cleanup path remain unchanged; a necessary stop does not wait for another host probe. |
| Matched busy/idle memory observations | Added a finite synthetic test with repeated workloads, normalized retained-prefix occupancy and comparable quiet samples. Interruptions are recorded separately from failures; neither is a pass. |
| Native Zig serving | Defer to a separate migration. Its [`draft.zig`](https://github.com/bertholomus/TensorFold/blob/4e80f05ecba89a4e90d16375ade2eddbdc0a10c4/zig/src/families/dsv41/draft.zig) caps streams at 16, and its native serving adapter couples the shared pool to context. Preserve our C32, 8,650,752-token shared pool, million-token request limit, Keys, vision, strict outputs and reversible host lifecycle before considering a cutover. |
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
required for these code changes.

## Finite qualification, October 9 Pacific / October 10 UTC

The qualified source is `32c4ebea7d0a81808aaa503d88ebe1a84612d0cf`, built as
`sha256:973b52dedb5e9e9270fdcaa1840f4ff61076c08fadb3d97c1aea98bef6795834`
on both hosts. All 478 source fingerprints and 473 installed runtime files were
checked; the 225-line dependency inventory matches the prior image. Models and
prepared caches were reused without changing their format or pins.

| Check | Result and scope |
|---|---|
| Offline contracts | 84 publication tests passed. |
| CUDA correctness | 22 tests passed per host: 16 poisoned-ring reproductions, four unaffected bitwise controls and two existing compaction controls. The attention tests use real dispatch/kernels with synthetic identity projection/norm/rotary stages. |
| Cold replay boundaries | All 42 requests passed: 14 lengths in three different orders, zero prefix hits, and matching complete SHA-256 output-token hashes per prompt. Each generated 64 tokens with deterministic sampling and ordinary decode. |
| Functional acceptance | All nine phases passed: text/vision, strict outputs, sampling, default/ordinary parity, full sessions, native million, admission, cancellation/recovery and mixed soak. |
| Default/ordinary parity | 104 matched reply pairs across C16, C24 and C32, including reversed mode order. These use the server's token-hash comparison, separately from the complete hashes in the replay test. |
| C32 capacity | Two waves of 32 sessions, each with 261,120 input plus 1,024 output tokens; both reached 32 active decoders and completed all replies. An identical primed document populated independent session states; this is not 32 independent cold document prefills. |
| Million-token capacity | 1,048,320 input plus 256 output tokens, all three planted facts recovered, and two concurrent small requests passed. This is a narrow retrieval/capacity test. |
| Mixed soak | Nine C32 waves / 288 requests completed over the requested six-minute soak. |

The [correctness receipt](../release/upstream-v06-correctness.json) and
[acceptance receipt](../release/upstream-v06-acceptance.json) contain sanitized
counts and private source-receipt hashes. Fixtures are synthetic; ordinary
inference traffic was not inspected or reused.

### Matched memory observations

Three repetitions used the same schemas and normalized retained-prefix set,
followed by 120 quiet seconds each. Each window provided 23 fresh watchdog
samples and the same resident-cache signature. The comparison uses the median
of each window's last six samples. Maximum later-window change relative to the
first window was:

| Counter | Head | Worker |
|---|---:|---:|
| Live glibc allocation (`uordblks + hblkhd`) | −0.004 MiB | +0.003 MiB |
| Rank anonymous RAM plus swap | +18.15 MiB | 0.00 MiB |

Both stayed within the predeclared 256 MiB growth bound. Graph captures remained
sealed at 96, with no GPU allocation OOMs or retries. This finite repeated-workload
result does not establish leak-free operation or resolve the earlier long-run
failure. New-schema diversity and much longer idle/busy runs remain different
workloads; the stopped 24-hour test was not resumed.

The acceptance client's five-second health observer timed out three times under
load, while inference assertions passed. Preserve those observations rather than
calling the entire run error-free. The paired watchdog has its own ten-second
health deadline; neither deadline nor the memory floor was relaxed for this test.

Across 772 watchdog observations before the deliberate fault, there were no
failed watchdog samples or optional host-probe errors. Minimum sampled available
RAM was 2.348 GiB on the head and 3.303 GiB on the worker. The head's roughly
0.35 GiB margin above the 2 GiB stop floor remains limited; a passing finite run
does not justify reducing that floor.

### Lifecycle and selected deployment

Normal stop/restoration passed before the update. Deliberately killing the idle
worker then exercised paired cleanup and host restoration in 44.7 seconds. The
fault correctly named `worker:container` / `rank-state`, retained a current head
observation and marked the last worker observation historical with its age.
The intentional fault remains in private evidence and is excluded from the
natural watchdog-failure count above.

The same candidate restarted successfully, passed its final text/vision smoke,
and was reachable from the worker through the LAN API. Both ranks retain the
same pinned image, read-only model/prepared mounts, Ethernet MTU 9000 and RDMA
MTU 4096. The paired monitor is active; the stopped endurance services remain
inactive. See the [lifecycle receipt](../release/upstream-v06-lifecycle.json).

The previous source `5ff2bd0db06b0efd5470512c8e30aa1c65eea348` and image
`sha256:bb2195c47f06c9952491d8197411eb02a9f748808fa30679f4fa31f483aaf7f8`
remain available, with private image/precompile selectors preserved. Prior-image
fallback and reboot recovery were not repeated. Later documentation commits do
not move the clean serving checkout from the source/image pair qualified here.
