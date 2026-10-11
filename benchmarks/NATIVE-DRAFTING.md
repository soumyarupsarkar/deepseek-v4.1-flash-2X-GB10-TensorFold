# Native drafting investigation

This work investigates the native C32 regression before further endurance
testing. The measured policy passed the repeated short C32 comparison and the
long-reply matrix, then failed full-window admission at the head's memory floor.
A request-memory correction is being qualified before accepting the candidate.
The 24-hour run remains stopped. See [migration status](../MIGRATION.md).

## Completed short C32 measurements

The measurements in the next two sections belong to source
`e3b0a9441c2855eb88433c7ac63697a1ff078e0d`, image
`sha256:4bada8d76afd5838900e423bcc2a2974208c9bb59223270231a9860ee0e69932`.
Compared with the instrumented baseline below, its three-repetition medians are:

| Temperature | Previous / candidate end-to-end tok/s | Change | Previous / candidate steady decode tok/s | Change |
| --- | ---: | ---: | ---: | ---: |
| 0 | 143.50 / 151.09 | +5.3% | 261.98 / 303.28 | +15.8% |
| 1 | 133.96 / 139.82 | +4.4% | 234.60 / 261.78 | +11.6% |

All 192 ordinary/drafted pairs matched, as did all 384 outputs against the
baseline. The ordinary controls changed less than 0.5% in both measures.
Greedy candidate end-to-end repetitions ranged from 150.84 to 151.29 tok/s;
sampled repetitions ranged from 139.56 to 140.19. These are synthetic 1,024-token
prompts with 256-token replies at observed C32, fixed seeds and zero actual
cache hits. Graph construction remains included in wall time.

Steady decode uses health-counter intervals at full requested decoder occupancy,
with no prefill or queued work. In the first greedy pair the candidate's eligible
interval was 12.03 seconds of a 54.31-second wave, versus 17.04 seconds of 56.88
previously. The different occupancy durations are retained with the rates;
the 15.8% steady improvement is not a whole-request improvement.

This does not make drafting universally faster. In the same candidate run,
ordinary decoding reached 163.25 greedy and 143.43 sampled end-to-end tok/s,
finishing these short waves sooner despite the candidate's stronger steady
decode rate. Longer replies, different concurrency and deep context require
their own comparisons. These native-to-native results also use a different
eviction protocol from the historical Python comparison.

## Long replies across concurrency

The complete matrix uses 1,024 prompt and 1,024 reply tokens per request, the
same synthetic fixtures and fixed seeds, and zero cached tokens. All 195
ordinary/drafted pairs matched, and all 390 outputs matched the baseline.
Each shape has one pair, so these are diagnostic observations rather than
repeated headline estimates. The table reports drafted end-to-end aggregate
tok/s; ordinary controls are retained in the evidence.

| Streams | Greedy previous / candidate | Sampled previous / candidate |
| ---: | ---: | ---: |
| 1 | 95.86 / 94.77 | 93.73 / 94.07 |
| 4 | 134.66 / 127.87 | 117.11 / 117.95 |
| 8 | 137.09 / 153.23 | 134.37 / 145.07 |
| 16 | 179.07 / 181.14 | 176.87 / 177.10 |
| 24 | 188.33 / 188.17 | 178.04 / 178.97 |
| 32 | 186.97 / 194.20 | 179.66 / 185.26 |

The extra greedy C12/C13 boundary checks reached 174.28/175.22 tok/s, versus
169.69/174.50 previously. No cliff appeared in that pair. C8 gained 11.8% greedy
and 8.0% sampled; C32 gained 3.9% and 3.1%. Greedy C4 regressed 5.0%, with its
ordinary control essentially unchanged. Separate repeated C1/C4/C8 confirmation
remains pending after the memory correction and feature validation.

The scarcity rule did not skip generation in that C4 wave. Its changed
allocation used 358 shared rounds versus 333 before, with verification taking
26.77 rather than 25.53 seconds. This points to a remaining allocation tradeoff;
the short-context cost prior is not optimal for every batch. Different windows
were verified, so these counters are not an isolated kernel-latency comparison.

## Full-window admission memory failure

The ordinary full-window C32 wave completed at 168.23 aggregate wave tok/s.
During admission of the following drafted wave, the head's available host memory
fell to 2,044.4 and 2,022.3 MiB in consecutive monitor samples, below the unchanged
2,048 MiB floor. The monitor stopped both ranks and restored their journaled host
state. All 32 client requests consequently disconnected; this is a failed deep
check, not a passing throughput result. The last health sample had no poisoned
runtime or RoCE fault, and the sampled cgroup had no OOM event.

Head-container anonymous memory rose about 476 MiB while the long requests were
admitted. A CPU reproduction found avoidable retained growth buffers in the
JSON parser's request arena: a 261,120-token numeric prompt, its body and typed
token IDs reserved 27,908,262 bytes. Reserving the flat numeric array once reduced
that to 16,255,238 bytes, about 355 MiB less across 32 such arenas. This is an
allocation-footprint measurement, not a demonstrated reduction in total physical
GPU memory. The buffers are released with the request; this was transient peak
memory rather than evidence of an unbounded leak.

The correction shares the original numeric scanner, preserves mixed/nested
array parsing and error messages, and avoids speculative large reservations for
malformed input. Regression tests cover a real full-window-sized input under a
16 MiB arena bound, numeric values, mixed arrays and malformed-input behavior.
The serving memory floor, host reserve, KV pool and context limits are unchanged.
The corrected image still needs the full hardware checks; the failed receipts
and images remain preserved.

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
