# Native drafting investigation

This work investigates the native C32 regression before further endurance
testing. The policy changes are candidates pending hardware validation. The
24-hour run remains stopped; these measurements do not qualify a production
cutover. See [migration status](../MIGRATION.md).

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
not undo the corrected table extrapolation. Exact rollback uses the retained
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
