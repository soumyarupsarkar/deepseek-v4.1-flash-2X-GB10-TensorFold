# Native drafting investigation

This work investigates the native C32 regression before further endurance
testing. The corrected parser candidate has passed the repeated short C32
comparison, complete long-reply matrix and deep C32 comparison, but failed
retention at the worker's host-memory floor. Both ranks are stopped and host
restoration passed. A bounded LRU graph-cache correction is awaiting hardware
validation. Neither failed candidate is qualified for cutover.
The 24-hour run remains stopped. See [migration status](../MIGRATION.md).

## Completed short C32 measurements

The current measurements belong to source
`455004e78522c4488dbb34b014adff1813d1ab73`, image
`sha256:5bacae70bf164d183c2230331f4e6661e8221f1fd5ca0b40683acdf293627b4a`.
Compared with the instrumented baseline below, its three-repetition medians are:

| Temperature | Previous / candidate end-to-end tok/s | Change | Previous / candidate steady decode tok/s | Change |
| --- | ---: | ---: | ---: | ---: |
| 0 | 143.50 / 146.00 | +1.7% | 261.98 / 286.35 | +9.3% |
| 1 | 133.96 / 134.51 | +0.4% | 234.60 / 257.86 | +9.9% |

All 192 ordinary/drafted pairs matched, as did all 384 outputs against the
baseline. These are synthetic 1,024-token prompts with 256-token replies,
observed C32, fixed seeds and zero actual cache hits. Graph construction remains
included in wall time. Greedy candidate end-to-end repetitions ranged from
145.16 to 147.19 tok/s; sampled repetitions ranged from 132.91 to 136.12.

Steady decode uses health-counter intervals at full requested decoder occupancy,
with no prefill or queued work. In the first greedy pair the candidate's eligible
interval was 14.03 seconds of a 55.65-second wave, versus 17.04 seconds of 56.88
previously. Eligible durations and counted tokens remain part of the evidence;
a steady-rate improvement is not a whole-request improvement.

The ordinary controls reached 160.07 greedy and 139.96 sampled end-to-end tok/s,
finishing these short waves sooner than drafting. Their end-to-end rates fell
2.1% and 2.7% against the earlier baseline, while their steady rates rose about
1%. Head swap activity and memory pressure were observed in this run. These
observations do not isolate the cause of timing variance. A separate C32 repeat
on the same warmed process was planned after the finite checks, but was not
run because retention failed. Any later confirmation will preserve both result
sets rather than replace the first run.

These native-to-native results use a different eviction protocol from the
historical Python comparison and must not be merged into that comparison.

## Long replies across concurrency

The complete matrix uses 1,024 prompt and 1,024 reply tokens per request, the
same synthetic fixtures and fixed seeds, and zero cached tokens. All 195
ordinary/drafted pairs matched, and all 390 outputs matched the baseline.
Each shape has one pair, so these are diagnostic observations rather than
repeated headline estimates. The table reports drafted end-to-end aggregate
tok/s; ordinary controls are retained in the evidence.

| Streams | Greedy previous / candidate | Sampled previous / candidate |
| ---: | ---: | ---: |
| 1 | 95.86 / 93.55 | 93.73 / 93.43 |
| 4 | 134.66 / 125.84 | 117.11 / 117.02 |
| 8 | 137.09 / 147.90 | 134.37 / 143.66 |
| 16 | 179.07 / 183.32 | 176.87 / 174.09 |
| 24 | 188.33 / 187.57 | 178.04 / 177.94 |
| 32 | 186.97 / 195.71 | 179.66 / 187.11 |

The extra greedy C12/C13 boundary checks reached 172.57/176.44 tok/s, versus
169.69/174.50 previously. No cliff appeared in that pair. C8 gained 7.9% greedy
and 6.9% sampled; C32 gained 4.7% and 4.1%. Ordinary C32 reached 194.38 greedy
and 180.13 sampled in this run. Greedy C4 regressed 6.6%, with its ordinary
control essentially unchanged; sampled C16 regressed 1.6%. Separate repeated
C1/C4/C8 confirmation was not run because feature validation failed.

The scarcity rule did not skip generation in the C4 greedy wave. Its changed
allocation used 358 shared rounds versus 333 before, with verification taking
26.21 rather than 25.53 seconds. This points to a remaining allocation tradeoff:
the short-context cost prior is not optimal for every batch. Different windows
were verified, so these counters are not an isolated kernel-latency comparison.

## Deep C32 comparison

The corrected image completed one ordinary and one drafted wave of 32 sessions,
each with 261,120 prompt tokens and 1,024 reply tokens. A primed identical
document supplies the retained prefix, with independent active session extents.
Priming is excluded from the reported aggregate wave rate.

| Mode | Previous / candidate aggregate wave tok/s |
| --- | ---: |
| Ordinary | 165.70 / 168.52 |
| Drafted | 169.73 / 172.30 |

The within-image reported token fingerprints matched for all 32 sessions;
all 64 mode/session fingerprints and usage counts also matched the baseline.
This one-wave performance client does not retain full token-ID digests.
The separate two-wave capacity gate checks actual SHA256 digests of complete
returned token-ID arrays, but did not run on this image. This is a diagnostic pair, not a repeated deep-speed
headline or a measurement of 32 simultaneous cold prefills.

## Earlier policy image and full-window memory failure

The preceding source `e3b0a9441c2855eb88433c7ac63697a1ff078e0d`, image
`sha256:4bada8d76afd5838900e423bcc2a2974208c9bb59223270231a9860ee0e69932`,
used the same drafting policy before the parser correction. Its short C32
medians were 151.09/139.82 end-to-end and 303.28/261.78 steady tok/s at
temperatures 0/1. Those stronger short results are retained as an earlier trial;
that image did not pass the deep gate. Its long matrix passed all 195 paired
and 390 baseline output comparisons.

Its ordinary full-window C32 wave completed at 168.23 aggregate wave tok/s.
During admission of the following drafted wave, the head's available host memory
fell to 2,044.4 and 2,022.3 MiB in consecutive monitor samples, below the unchanged
2,048 MiB floor. The monitor stopped both ranks and restored their journaled host
state. All 32 client requests consequently disconnected; this was a failed deep
check. The last health sample had no poisoned runtime or RoCE fault, and the
sampled cgroup had no OOM event.

Head-container anonymous memory rose about 476 MiB while the long requests were
admitted. A CPU reproduction found avoidable retained growth buffers in the
JSON parser's request arena: a 261,120-token numeric prompt, its body and typed
token IDs reserved 27,908,262 bytes. Reserving the flat numeric array once reduced
that to 16,255,238 bytes, about 356 MiB less across 32 such arenas. This is an
allocation-footprint measurement, not a demonstrated reduction in total physical
GPU memory. These benchmark clients close their connections, releasing the
arenas. Persistent connections retain arena capacity for reuse until they close.
This demonstrates avoidable allocation overhead, not an unbounded leak.

The correction shares the original numeric scanner, preserves mixed/nested
array parsing and error messages, and avoids speculative large reservations for
malformed input. Regression tests cover a synthetic full-window-sized input
under a 16 MiB arena bound, numeric values, mixed arrays and malformed-input
behavior. All 90 image-build steps and 313 tests passed. Both hosts passed seven
GPU checks, all 48 router widths, and the full 143,770-entry, 106,107,109,192-byte
prepared-cache comparison with zero mismatches. The serving memory floor, host
reserve, KV pool and context limits are unchanged. The corrected deep comparison
passed. Baseline, structured output, sampling, aliases, protocols and both
constraint modes passed, but retention then failed. The failed receipts and
images are preserved.

## Worker retention failure and graph-cache correction

On the corrected parser image, the worker crossed the unchanged 2 GiB host
memory floor during the 32-prefix retention test. The last health report had
56 checkpoints, about 357 MiB of snapshot buffers, and 261 resident round graphs.
No OOM event or RoCE poison was observed. The monitor stopped both ranks, and
fresh restoration checks passed on both machines. The two-wave full-capacity,
million-token and repeated low-concurrency gates did not run.

The existing graph cache accumulated shapes across row counts and context
buckets, up to 512 entries, then ran unseen shapes eagerly. Worker-container
anonymous memory had reached about 2.18 GiB before retention; it stayed roughly
flat during retention while checkpoint allocations reduced available memory.
This evidence identifies accumulated graph overhead plus snapshot demand as a
headroom problem; it does not attribute every byte of host-memory change to
CUDA graphs or prove that the drafting policy caused the failure.

The next candidate uses a 144-entry least-recently-used cache. This can hold all
48 row widths and three stretches for one context bucket. New shapes evict cold
executables and are captured normally, preserving graph replay for the active
working set. The engine's default limit remains 512; the deployment profile
selects 144. This trades possible recapture latency when workloads alternate
between many shapes for bounded resident graph overhead. KV capacity, 64-state
retention, 32 stream slots, the million-token request window and the host memory
floor remain unchanged.

Resident graphs, cumulative captures and evictions have separate counters.
Capture-time exclusions in cost calibration use the cumulative counter, so
replacement at a full cache cannot masquerade as a warm replay. CUDA permits
an executable to be destroyed while its launched work finishes asynchronously;
its backing model buffers remain live. See NVIDIA's
[CUDA graph API reference](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__GRAPH.html).
CPU tests cover eviction order, hot-shape retention and bounded context churn;
the GPU graph check also verifies completion after immediate executable
destruction. Hardware memory savings and final throughput remain unverified.

## Measured cause

Our C32 integration made 48 verification rows available, but the native adapter
still repeated the 24-row cost table's last value through row 48. That made extra
verification rows appear free to the allocator. The generation budget also proposes tokens before
deciding which proposals are worth verifying. With C32, that can pay for two
drafter passes and a wider target forward without sufficient accepted tokens.

An instrumented repeat at runtime source
`7d7ddd39d446c43f7048f9f61c2516f861f870b0`, image
`sha256:b67586ba247357e9b3f73cd04ea91eaee27487fb9bec5b2f888d3f0af0d3323d`,
confirmed the regression. These are medians of three repetitions per mode,
using synthetic mixed prompts, 1,024 prompt tokens and 256 reply tokens per
request, seed 42000, and observed C32 decoding:

| Temperature | Ordinary end-to-end tok/s | Existing drafting end-to-end tok/s | Ordinary steady decode tok/s | Existing drafting steady decode tok/s |
| --- | ---: | ---: | ---: | ---: |
| 0 | 163.44 | 143.50 | 293.31 | 261.98 |
| 1 | 143.78 | 133.96 | 235.13 | 234.60 |

All 192 ordinary/drafted pairs matched full-text and reported token hashes.
All 384 outputs also matched the uninstrumented reference. Instrumentation's
median end-to-end differences were within 0.6%; this is negligible measured
overhead, not evidence of a speed improvement.

Across the three T0 repetitions, ordinary verification took 82.35 seconds.
Drafted verification took 91.08 seconds, plus 12.37 seconds generating drafts.
Logits transfer and CPU sampling accounted for about 2% of measured T1 decode
time; scheduler bookkeeping was negligible. Verification includes GPU compute,
device communication and draft-state absorption. These counters do not isolate
device RDMA or rule it out as part of that cost.

The prompts are shorter than the native 2,048-token retained-state checkpoint.
The diagnostic omits retained-prefix eviction and requires zero actual cached
tokens in every wave. This differs from the earlier Python/native comparison's
full eviction protocol; the numbers must not be merged into that comparison.
Graph construction stays in benchmark wall time but is excluded from forward
cost calibration. The fixtures contain no user inference traffic.

The [baseline evidence](../release/native-throughput-baseline-20261010.json)
also preserves the complete 28-wave, 1,024-reply-token matrix. All 195 paired
outputs matched. Drafting improved end-to-end throughput at C1 through C24;
at C32 it was 2.9% slower for greedy decoding and approximately even for sampled
decoding. These longer replies therefore show a smaller C32 penalty than the
256-token replies. There was no throughput cliff in the greedy C12/C13 pair.
Each long shape has one pair, so these are diagnostic observations rather than
repeated headline estimates.

## Candidate changes

Incomplete forward-cost tables now extrapolate from the final cost per row,
instead of repeating the final cost. A separate `TF_DS_SHARED_ROUND_MS` override
supplies the calibrated shared-forward prior while preserving the solo table.
The [calibration record](../deployment/config/native-shared-costs-20261010.json)
uses warm observations at widths 1, 4, 8, 12, 16, 24, 32 and 48, with linear
interpolation elsewhere. It equally weights greedy and sampled means. This is
a short-context prior, not a claim that one curve describes every prompt and
context length.
The lane core explicitly keeps single-window allocation on its solo costs for
this backend; other backends retain their existing allocation behavior.

`TF_DS_ADAPTIVE_DRAFTS=1` enables an empirical shared-generation guard. It learns
committed tokens per total round time, including verification and generation,
separately for each live stream count, context bucket and greedy/sampled class.
It gathers four valid rounds per mode, requires a 3% advantage to select
drafting, and retries the other mode after 64 settled rounds. New or mixed mode
transitions, graph construction and rounds interleaved with active prefill do
not train the estimates. Measurements
are workload dependent; this is not a fixed concurrency cutoff.
The learned rates live in memory and reset when the serving process restarts.
After at least four settled rounds, a selected drafter whose measured rate falls
below the plain estimate triggers an early plain probe. This avoids retaining a
losing preference for the entire 64-round interval; the probe refreshes the
alternative measurement before selecting again. The 3% entry margin and 0%
early-withdrawal threshold provide hysteresis.

Suppressing generation keeps target-state absorption active so drafting can
resume. It can still use a valid copied continuation. This differs from a
client explicitly requesting ordinary decoding with `draft:false`. Solo
generation, sampling, acceptance and forced reasoning closure are unchanged.
No GPU kernel, pass width, KV allocation or context limit changes are involved.
All 32 streams remain eligible for drafting within the existing 48-row budget.

The first two hardware candidates combined this calibrated prior with the
empirical guard. Both preserved all 384 short-benchmark outputs, but neither
closed the short-reply C32 gap. The first candidate's median greedy end-to-end
rate was 147.78 tok/s and sampled rate 133.19 tok/s. Earlier withdrawal in the
second candidate gave 144.99 and 133.96 tok/s. These mixed results do not justify
claiming that the empirical guard is a demonstrated throughput improvement.

The third candidate disabled that guard in the deployment profile and enabled
`TF_DS_BUDGET_DRAFTS=1`. Its three-repetition C32 short benchmark preserved all
192 within-revision pairs and all 384 outputs against the baseline. Median
steady decode improved about 10.5% at both temperatures (261.98 to 289.62 tok/s
greedy; 234.60 to 259.17 sampled), while end-to-end throughput changed +0.9% and
-1.2%. Those are different measures; the cold-wave total did not gain 10.5%.
Its long C4 greedy pair regressed to 119.75 tok/s from 134.66, with the ordinary
control essentially unchanged. That trial was stopped after six complete long
waves to refine the rule; it did not complete the deep or feature gates.

The current candidate applies bounded probes only when mandatory verifier rows
leave fewer free rows than eligible draft streams. Mandatory rows include
ordinary target rows and forced continuations. When there is room to offer one
speculative row to each eligible stream, generation resumes immediately and
the waiting counters reset. This covers smaller batches and draining tails;
it is a row-budget condition rather than a fixed concurrency cutoff.

Under that scarcity condition, the policy uses the last shared allocation to
avoid regenerating proposals for a stream granted zero speculative verification
rows. Each eligible
zero-grant stream gets a one-proposal probe every eight shared budget decisions;
a positive allocation resumes generation immediately. Streams with unknown
allocation, solo generation and forced closes retain their existing behavior.
This preserves all-stream eligibility without requiring generation for all 32
streams on every round. A probe is an opportunity, not a guarantee that the
allocator will accept a proposal. Draft-state absorption remains active.

This targets a measured mismatch: at C32, the 48-row verifier has only 16 rows
left after each stream's mandatory target row, while the previous generation
budget allowed two extra proposals even for zero-grant streams. The native
drafter computes five hidden rows per selected stream regardless of requested
depth, so avoiding a whole stream's generation can save more work than merely
shortening its proposed chain. The pass width and GPU kernels are unchanged.
The bounded-probe policy and guard-off profile formed the third candidate, not
an isolated one-variable ablation. The scarcity refinement requires renewed
hardware checks before selecting it as the deployment default.

The health diagnostics report measured drafted/suppressed rounds, probe rounds,
excluded transitions/captures/prefill, suppressed stream requests and completed draft
rounds that generated for all 32 streams. Optional `TF_DS_MEASURE_COSTS=1`
provides bounded timing counters and cost tables at idle, without additional
GPU synchronization.

## Validation and rollback

The long-reply diagnostic compares ordinary and drafted decoding at C1, C4,
C8, C16, C24 and C32, at temperatures 0 and 1. C12/C13 checks cover the drafter
kernel boundary. One pair per shape is diagnostic; repeated C32 short-reply
measurements and representative deep-context/capacity checks are separate.
Candidate results will be recorded after compilation and hardware validation.

Setting `TF_DS_ADAPTIVE_DRAFTS=0` disables the generation guard; unsetting
`TF_DS_SHARED_ROUND_MS` removes the calibrated shared prior. These switches do
not undo the corrected table extrapolation. `TF_DS_BUDGET_DRAFTS=0` restores
generation slack for zero-grant streams. Both policy switches default off in
the engine; their deployment choices are explicit in the profile. Exact rollback uses the retained
source and image, through the owned deployment controller. Stop both current
ranks and verify host restoration before switching revisions. Keep the current
ownership and restoration journals; never replace them with an earlier
launch's active-state files. Follow the
[native/Python rollback runbook](../deployment/MIGRATION-ROLLBACK.md) for the
retained Python deployment, including its qualified cold-start helper.

The configured limits remain an 8,650,752-token shared pool, 32 live slots,
1,048,576 tokens per request and 48 rows per shared round. Earlier capacity and
feature passes belong to their recorded images; policy changes require renewed
checks before they can inherit those claims.
