# Native drafting investigation

This completed phase investigates the native C32 regression before further
endurance testing. The current candidate passed the repeated short C32
comparison, complete long-reply matrix, deep C32 comparison, all 11
serving/capacity gates, repeated low-concurrency checks and a later C32
confirmation. Both test ranks are stopped and host restoration passed.
Earlier candidates' memory failures remain documented below. The 24-hour run
remains stopped; production cutover is held. See
[migration status](../MIGRATION.md) and the
[complete sanitized evidence](../release/native-throughput-policy-20261010.json).

## Completed short C32 measurements

The current measurements belong to source
`6aaec5b3616f4547fabbe2fcc3fb1e779bb75f82`, image
`sha256:baa3fc8d748766476d694da36f3e79ac501f18bed6b9572e36c1c80c4baa7bc7`.
Compared with the instrumented baseline below, its three-repetition medians are:

| Temperature | Previous / candidate end-to-end tok/s | Change | Previous / candidate steady decode tok/s | Change |
| --- | ---: | ---: | ---: | ---: |
| 0 | 143.50 / 149.59 | +4.2% | 261.98 / 290.08 | +10.7% |
| 1 | 133.96 / 140.48 | +4.9% | 234.60 / 261.27 | +11.4% |

All 192 ordinary/drafted pairs matched, as did all 384 outputs against the
baseline. These are synthetic 1,024-token prompts with 256-token replies,
observed C32, fixed seeds and zero actual cache hits. Repetitions reuse the same
fixtures; the 384 matches are not 384 independent unique prompts. Two unscored
T0 warm-ups precede the scored pairs, with pair order reversed in repetition 2.
Graph construction remains included in wall time. Greedy candidate end-to-end
repetitions ranged from 148.58 to 149.72 tok/s; sampled repetitions ranged from
140.33 to 141.27.

Steady decode uses health-counter intervals at full requested decoder occupancy,
with no prefill or queued work. In the first greedy pair the candidate's eligible
interval was 14.03 seconds of a 54.71-second wave, versus 17.04 seconds of 56.88
previously. Eligible durations and counted tokens remain part of the evidence;
a steady-rate improvement is not a whole-request improvement.

The ordinary controls reached 162.95 greedy and 142.84 sampled end-to-end tok/s,
finishing these short waves sooner than drafting. Their end-to-end and steady
rates stayed within 1% of the earlier ordinary baseline. The later repeat below
retains a separate result set because host and graph state can affect timing.

These native-to-native results use a different eviction protocol from the
historical Python comparison and must not be merged into that comparison.

## Later C32 confirmation

After all serving/capacity gates and the low-concurrency confirmation, the same
process repeated the short C32 protocol: two unscored T0 warm-ups and three
scored pairs per temperature, with the second repetition's order reversed.
All 192 ordinary/drafted pairs and all 384 baseline output comparisons matched.
These repeated fixtures do not add independent unique prompts.

| Temperature | Ordinary end-to-end tok/s | Drafted end-to-end median (range) | Drafted steady median (range) |
| --- | ---: | ---: | ---: |
| 0 | 163.16 | 149.15 (149.15–149.54) | 289.20 (286.74–290.03) |
| 1 | 143.32 | 140.89 (140.11–141.37) | 259.93 (258.56–261.30) |

The later drafted medians were 3.9%/5.2% above the original end-to-end baseline
and 10.4%/10.8% above its steady rates. The ordinary steady medians were
292.13/233.89 tok/s. This supports the initial result across the intervening
workload changes; it does not replace the initial repetitions or isolate a
code change from host state. The two runs are not pooled into one headline.

## Long replies across concurrency

The complete matrix uses 1,024 prompt and 1,024 reply tokens per request, the
same synthetic fixtures and fixed seeds, and zero cached tokens. All 195
ordinary/drafted pairs matched, and all 390 outputs matched the baseline.
Each shape has one pair, so these are diagnostic observations rather than
repeated headline estimates. The table reports drafted end-to-end aggregate
tok/s; ordinary controls are retained in the evidence.

| Streams | Greedy previous / candidate | Sampled previous / candidate |
| ---: | ---: | ---: |
| 1 | 95.86 / 94.94 | 93.73 / 91.33 |
| 4 | 134.66 / 129.87 | 117.11 / 116.59 |
| 8 | 137.09 / 146.25 | 134.37 / 143.50 |
| 16 | 179.07 / 179.06 | 176.87 / 176.78 |
| 24 | 188.33 / 185.90 | 178.04 / 180.11 |
| 32 | 186.97 / 193.48 | 179.66 / 185.55 |

The extra greedy C12/C13 boundary checks reached 173.41/175.19 tok/s, versus
169.69/174.50 previously. No cliff appeared in that pair. C8 gained 6.7% greedy
and 6.8% sampled; C32 gained 3.5% and 3.3%. In this initial matrix, greedy C4
regressed 3.6% and sampled C1 regressed 2.6%. The separate confirmation below
retains those initial results while checking their repeatability.

The scarcity rule did not skip generation in the C4 greedy wave. Its changed
allocation used 358 shared rounds versus 333 before, with verification taking
26.32 rather than 25.53 seconds. This points to a remaining allocation tradeoff:
the short-context cost prior is not optimal for every batch. Different windows
were verified, so these counters are not an isolated kernel-latency comparison.

## Repeated C1/C4/C8 confirmation

After the feature and capacity gates, three ordinary/drafted pairs per selected
shape used the same 1,024-token prompts, 1,024-token replies and fixed seeds.
The second repetition reversed order. All 66 paired comparisons and all 132
baseline output comparisons matched. These repeat the fixtures, rather than
introducing 132 unique prompts.

| Streams / temperature | Previous single pair tok/s | Candidate drafted median tok/s | Candidate drafted range | Change |
| --- | ---: | ---: | ---: | ---: |
| 1 / 0 | 95.86 | 95.95 | 95.61–96.04 | +0.1% |
| 1 / 1 | 93.73 | 94.27 | 93.94–94.32 | +0.6% |
| 4 / 0 | 134.66 | 131.42 | 129.42–132.21 | −2.4% |
| 8 / 0 | 137.09 | 149.18 | 148.92–149.30 | +8.8% |
| 8 / 1 | 134.37 | 144.73 | 139.89–144.95 | +7.7% |

The initial sampled C1 slowdown did not persist in these repetitions. C4's
tradeoff did persist. The final sampled C8 pair slowed in both modes: ordinary
fell to 112.79 tok/s from 119.31/119.51, and drafted to 139.89 from
144.73/144.95. All repetitions remain in the evidence. The baseline has one
long pair per shape from an earlier serving process; this is a confirmation of
candidate behavior, not a contemporaneous multi-repetition baseline comparison.

## Deep C32 comparison

The current image completed one ordinary and one drafted wave of 32 sessions,
each with 261,120 prompt tokens and 1,024 reply tokens. A primed identical
document supplies the retained prefix, with independent active session extents.
Priming is excluded from the reported aggregate wave rate.

| Mode | Previous / candidate aggregate wave tok/s |
| --- | ---: |
| Ordinary | 165.70 / 164.72 |
| Drafted | 169.73 / 172.14 |

The within-image reported token fingerprints matched for all 32 sessions;
all 64 mode/session fingerprints and usage counts also matched the baseline.
This one-wave performance client does not retain full token-ID digests.
The separate two-wave capacity gate checks actual SHA256 digests of complete
returned token-ID arrays; that gate also passed. This is a diagnostic pair,
not a repeated deep-speed headline or a measurement of 32 simultaneous cold
prefills.

## Renewed capacity and serving checks

These checks belong to the current `6aaec5b` image, independently of the
earlier migration image's results:

| Area | Completed check |
| --- | --- |
| Build and preparation | 90/90 build steps, 315/315 CPU/server tests; seven GPU checks on each host, including all 48 router widths and graph destruction with queued work |
| Prepared tensors | All 143,770 entries and 106,107,109,192 bytes compared on each host; zero byte or layout mismatches against the intended Keys checkpoint |
| Serving features | Synthetic text and vision, JSON/schema/tools, sampling, aliases and API protocols; C32 schemas/tools at temperatures 0 and 1 |
| Retention | 32 distinct 16k histories: cold admission, replay, extension and extended replay; 64 checkpoints and 408 MiB snapshot storage |
| C32 burst | 2,048 prompt and 1,024 reply tokens per request; one concurrent reply's reported token fingerprint matched the same request run alone |
| Full-window C32 | Two waves of 32 sessions, each with 261,120 prompt plus 1,024 reply tokens; all 32 complete token-ID SHA256 digests matched across waves |
| Million-token request | 1,048,320 uncached prompt tokens plus 256 reply tokens; all three passphrases retrieved; the small arithmetic and JSON requests finished during prefill in 0.872 s and 2.162 s |

The shared pool remains 8,650,752 tokens, with 32 slots, a 1,048,576-token
request limit and 48 round rows. The full-window C32 test uses a primed identical
document with independent active extents. These are finite correctness and
capacity checks. Earlier recovery, compaction and endurance observations retain
their original image identities; this phase does not renew those claims.

## Earlier policy image and full-window memory failure

An earlier source, `e3b0a9441c2855eb88433c7ac63697a1ff078e0d`, image
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
behavior. The parser-only candidate passed all 90 image-build steps and 313
tests. Both hosts passed seven GPU checks, all 48 router widths, and the full
143,770-entry, 106,107,109,192-byte
prepared-cache comparison with zero mismatches. The serving memory floor, host
reserve, KV pool and context limits are unchanged. The corrected deep comparison
passed. Baseline, structured output, sampling, aliases, protocols and both
constraint modes passed, but retention then failed. The failed receipts and
images are preserved.

## Worker retention failure and graph-cache correction

On source `455004e78522c4488dbb34b014adff1813d1ab73`, image
`sha256:5bacae70bf164d183c2230331f4e6661e8221f1fd5ca0b40683acdf293627b4a`,
the worker crossed the unchanged 2 GiB host
memory floor during the initial cache-eviction step of the retention test:
64 sequential synthetic 4,096-token requests. The eviction call did not return,
so the intended 32-prefix cold/replay/extension stages never began. The last
health report had 56 checkpoints, about 357 MiB of snapshot buffers, and 261
resident round graphs.
No OOM event or RoCE poison was observed. The monitor stopped both ranks, and
fresh restoration checks passed on both machines. The two-wave full-capacity,
million-token and repeated low-concurrency gates did not run.

That failed image's short C32 medians were 146.00/134.51 end-to-end and
286.35/257.86 steady tok/s at temperatures 0/1. Its long C32 rates were
195.71/187.11, and deep ordinary/drafted rates were 168.52/172.30. All short
and long output comparisons passed, but those measurements did not qualify
the image for continued serving. They remain part of the trial history.

The existing graph cache accumulated shapes across row counts and context
buckets, up to 512 entries, then ran unseen shapes eagerly. Worker-container
anonymous memory had reached about 2.18 GiB before retention; it stayed roughly
flat during retention while checkpoint allocations reduced available memory.
This evidence identifies accumulated graph overhead plus snapshot demand as a
headroom problem; it does not attribute every byte of host-memory change to
CUDA graphs or prove that the drafting policy caused the failure.

The current candidate uses a 144-entry least-recently-used target-round cache.
This can hold all 48 row widths and three stretches for one context bucket.
New shapes evict cold
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
destruction. Both hosts passed that GPU check. The deep and retention checks
exercised actual replacement while residency stayed bounded, and retention
passed on this image. This does not isolate physical driver memory savings.

## Observed memory and graph limits

The paired monitor retained 1,491 samples per host, from 09:31:33 to 11:44:06
UTC on October 11. No sampled memory-floor crossing, OOM or OOM kill occurred.
The head's minimum `MemAvailable` was **2.026 GiB**, only **26.6 MiB above the
2 GiB floor**, during the second full-window C32 wave. The worker's minimum was
3.084 GiB. The head's maximum sampled container swap was 2.498 GiB and its
maximum memory-pressure `full avg10` was 13.34%; worker swap remained zero.
Passing the finite tests with this narrow margin does not establish adequate
production headroom or endurance stability.

The benchmark clients and diagnostic reader ran on the head. At 10:58:24 UTC,
the progress reader stopped reparsing two completed large result files at each
poll, reducing its temporary allocations. This was just after the minimum
sample; runtime and benchmark-client inputs were unchanged. Its isolated memory
effect was not measured, so these observations describe the complete test host.

All 84 reviewed benchmark-wave boundaries respected the 144-entry graph limit;
captures minus evictions equaled resident entries at idle. There were 222
evictions inside those wave intervals and no eager fallback or reported RDMA
failure. Across the complete campaign, the monitor observed up to 648 captures
and 504 evictions, leaving 144 resident executables. Other feature and warm-up
intervals account for the additional replacements. Capture counters include
recaptures; bounded residency is not a measurement of physical driver-memory
savings.

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
an isolated one-variable ablation. The scarcity refinement is selected in this
candidate's deployment profile; its completed measurements and qualification
limits are reported above.

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
The current image independently passed the 11 serving/capacity gates above,
90/90 build steps, 315/315 CPU/server tests, GPU checks and full prepared-cache
comparison on both hosts. The 75 publication tests also passed. The
[evidence export](../release/native-throughput-policy-20261010.json) retains
every scored repetition, earlier trial results, timing-window counts, input
hashes and the observed memory limits. Fixtures are synthetic; no user inference
traffic was used. Private operational records remain outside the repository.

Setting `TF_DS_ADAPTIVE_DRAFTS=0` disables the generation guard; unsetting
`TF_DS_SHARED_ROUND_MS` removes the calibrated shared prior. These switches do
not undo the corrected table extrapolation. `TF_DS_BUDGET_DRAFTS=0` restores
generation slack for zero-grant streams. Both policy switches default off in
the engine; their deployment choices are explicit in the profile. Exact rollback
uses the retained source and image, through the owned deployment controller.
Stop both current
ranks and verify host restoration before switching revisions. Keep the current
ownership and restoration journals; never replace them with an earlier
launch's active-state files. Follow the
[native/Python rollback runbook](../deployment/MIGRATION-ROLLBACK.md) for the
retained Python deployment, including its qualified cold-start helper.

The configured limits remain an 8,650,752-token shared pool, 32 live slots,
1,048,576 tokens per request and 48 rows per shared round. Both ranks stopped
through the controller after testing; the fresh restoration check at
11:44:32 UTC on October 11 reported no host-setting differences. Source, images,
weights, prepared caches and rollback records are retained. This phase does not
renew the earlier image's compaction, recovery or Python rollback rehearsal,
and does not authorize endurance or production cutover.
