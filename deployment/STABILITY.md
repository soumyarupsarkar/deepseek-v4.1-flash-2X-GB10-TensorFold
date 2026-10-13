# Native stability and host-memory investigation

The bounded diagnostic runs the current serving image for up to twelve hours,
then finishes with a matched quiet-memory observation. The initial run used
four hours; the secondary observation uses twelve. It preserves the running
ranks, model settings and LAN endpoint. Leave other inference clients idle:
unexpected completed requests invalidate a wave or quiet interval.

The workload repeats 32 concurrent requests: 29 synthetic text tasks, a strict
JSON response, a required tool call and an image-color check. A fixed-seed solo
canary must keep its output-token hash. Every fourth cycle adds a cold request,
rotating through 32,768, 131,072, 262,144, 614,400 and 1,048,320 prompt tokens,
with 256 reply tokens. Deep requests are omitted during the last 15 minutes.

At baseline, roughly hourly and at the end, 64 fixed-size synthetic requests
replace retained prefixes with 4K histories. The client then records two quiet
minutes without inference. Compare these matched intervals, including actual
retained-state counts, snapshot bytes and graph occupancy; ordinary busy/idle
memory differences alone do not establish a leak.

The existing paired watchdog continues enforcing its 2 GiB available-memory
floor and health/progress checks. A bounded per-run file copies its numeric host
samples approximately every ten seconds, including rank RSS, anonymous/file
memory, swap, pressure and OOM counters. Quiet endpoints also take detailed
process-memory samples. Raw prompts and response text are not stored by this
client. Each evidence stream is limited to 64 MiB.

## Start and inspect

Use a clean checkout that owns the serving deployment. The diagnostic requires
a matching finite feature/C32/million-token receipt, running rank identity,
source/image/profile agreement and an active watchdog. It does not claim the
separate recovery/rollback gates or a 24-hour release qualification.

From the recipe checkout containing the updated client:

```bash
python3 -B tools/qualification/native_endurance.py \
  --source /absolute/path/to/serving-checkout \
  --diagnostic-prerequisites /path/to/matching-feature-and-capacity-receipt.json \
  --record native-twelve-hour-UNIQUE \
  --hours 12
```

The initial run used
[`native-throughput-policy-20261010.json`](../release/native-throughput-policy-20261010.json)
for runtime `6aaec5b3`. A new image needs its own matching finite prerequisites;
the client rejects evidence from a different source or image.

Choose a fresh record name. Evidence lives in the serving checkout under
`deployment/.local/qualification/endurance/<record>/`:

- `status.json`: phase, progress, source/image, target finish, final memory summary.
- `cycles.jsonl`: mixed/deep results, replay checks and detailed quiet endpoints.
- `memory.jsonl`: bounded numeric samples copied from the watchdog.

For an unattended run, use a transient systemd service with `Restart=no`,
`RuntimeMaxSec=12h20m` and `TimeoutStopSec=30s`, running as the deployment user.
The extra service allowance covers an in-flight wave and final quiet sampling;
it does not start a second test or extend the twelve-hour workload schedule.
Record the exact unit name and command alongside the receipt before launch.

Stopping that test unit interrupts only its client. The inference watchdog
continues operating. There is no automatic test or rank restart. A serving or
correctness failure stops the owned pair; unrelated inference traffic stops
the observation without intentionally stopping a healthy server. Interrupted
and failed runs remain preserved and are never counted as passes.

After normal completion the server stays available. `diagnostic-workload-passed`
means the workload completed; `memory_review: pending` remains until the quiet
comparisons and continuous memory history have been reviewed. A lower idle RSS
caused by more swap is not evidence of reduced memory consumption.

Review rank-process `RssAnon + VmSwap` alongside live glibc allocations,
grammar-cache bytes and matched snapshot/graph occupancy. Allow cache warm-up;
look for a sustained plateau afterward. Keep the cgroup counters separate:
anonymous memory plus cgroup swap charges is not a live-heap measurement.
The twelve-hour run adds confidence in sustained mixed-load stability and
keeps the same image, capacity, watchdog floor and failure behavior.

## Twelve-hour result and subsequent incident

The subsequent twelve-hour run on runtime `84ae3aaa` completed in 12 hours
5 minutes 12 seconds: 14,662 requests, 66.3 million input tokens, 880,523 output
tokens, 289 mixed C32 waves, 67 cold deep-context waves and 291 matching canaries.
Matched quiet endpoints grew by 4.29 MiB on the head and 2.92 MiB on the worker.
There were no OOMs, poisoned runtimes, RoCE failures or rank restarts. Minimum
available memory was 2.85 GiB and 3.16 GiB, respectively.

Later concurrent agent traffic triggered a protective low-memory shutdown.
The [text-prompt investigation](REQUEST-MEMORY.md) reproduces a separate
request-arena retention problem and documents its correction. The twelve-hour
result covers its stated workload; it does not establish that long concurrent
text prompts have the same CPU-memory requirements as token-array inputs.

## Initial result and memory investigation

The October 11, 2026 run completed 107 mixed C32 waves, 22 cold deep-context
waves (including four million-token requests), and 109 matching fixed-seed
canaries. There were no correctness failures, poisoned runtimes, OOM events or
rank restarts. Including final normalization and quiet sampling, it took
4 hours 4 minutes 42 seconds. This was the requested four-hour observation,
not the separate 24-hour endurance qualification.

Across matched quiet endpoints, the head rank processes' `RssAnon + VmSwap`
increased by 311 MiB. The broader container indicator (`memory.stat anon` plus
`memory.swap.current`) increased by 539 MiB; the worker's container indicator
increased by 21 MiB. The grammar cache grew by 170 MiB during warm-up, but head
process growth continued after it levelled off. Snapshot residency stayed at
64 states / 408 MiB. Graph residency stayed within its 144-executable limit.

These process and container indicators are kept separate. Container swap
accounting includes additional charges, and swap-cache pages can count against
both memory and swap usage ([Linux cgroup documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)).
The final review uses the process snapshots already recorded during the tests;
it does not treat the larger container indicator as live heap bytes or subtract
swap-cache counters that were not collected at the earlier endpoints.

Component controls separated ordinary request handling from grammar churn:
2,000 health requests, 256 tokenization requests and 256 plain C32 inference
requests showed little head growth. Repeating one schema was also stable after
warm-up. The four-hour workload varied a required numeric value between cycles;
the control used that same schema family. Cycling through 128 schemas then added
57 MiB of process anonymous memory plus swap (113 MiB in the container indicator),
with essentially unchanged grammar-cache size and unchanged graph residency.
In a disposable
CPU-only process using the same pinned grammar library and tokenizer, live
glibc allocations plateaued while freed arena space grew; an explicit trim
returned about 79 MiB in the published reproducer. This establishes allocator
retention as a contributor; the grammar-cache byte counter alone does not
describe total host memory.

The profile now fixes glibc's automatic trim threshold at 128 KiB. The isolated
repeat control with that setting stayed at 253.2 MiB of anonymous memory plus
swap after warm-up, versus growth from 286.2 to 316.8 MiB with defaults over
1,536 further compilations. Compiled-cache occupancy remained 182.7 MiB in both
cases. The repeated compilation phase took 7.22 seconds with the setting versus
1.81 seconds with defaults, so memory reclamation is not free. Serving latency
and throughput need their own measurements; the CPU result alone does not
establish serving performance or indefinite stability.

The CPU control is reproducible with
[`native_grammar_heap.py`](../tools/qualification/native_grammar_heap.py). Run it
in a disposable instance of the pinned serving image with no GPU access, a
read-only `/model` mount and a memory limit. It never contacts the inference
server. Compare a default process with one launched using
`MALLOC_TRIM_THRESHOLD_=131072`; `--trim-at-end` optionally measures how much
this disposable process can return after its repeated work. Output contains
only synthetic-test metadata, input hashes and numeric memory/cache samples.

## Serving follow-up

Runtime `84ae3aaa` passed the fresh text/vision/structured-output checks, two
waves of 32 full 262k sessions with all fixed-seed token sequences matching,
and a cold million-token retrieval check. The latter recovered three passphrases
at 10%, 50% and 90% depth, generated the full 256-token reply and reached
1,048,576 total tokens in 671 seconds.

The component follow-up completed 64 tokenization and 576 inference requests.
After warming the same family of 128 schemas, its repeated cycles showed:

| 128-schema cycle | Rank process anon + swap change | Container anon + swap indicator | Grammar-cache growth | New graph captures |
|---|---:|---:|---:|---:|
| Previous image, warm control | +57.19 MiB | +113.11 MiB | 0.04 MiB | 0 |
| Trim policy, first warm repeat | −0.03 MiB | +2.03 MiB | 0 | 0 |
| Trim policy, second warm repeat | −0.02 MiB | +0.10 MiB | 0 | 0 |

Live glibc allocation growth was only 2,528 and 896 bytes in the two warm
repeats; free arena space stayed around 2 MiB. Their elapsed times were 68.9 and
67.9 seconds, compared with 68.2 seconds for the earlier control, including the
same pauses and memory sampling. These results address the large retention
pattern reproduced from the four-hour run.

The first varying-schema cycle on the new process warmed 157.3 MiB of grammar
cache and added 161.6 MiB of process anonymous memory plus swap (151.7 MiB in the
container indicator). That cold-cache increase is kept separate from the
warm-repeat comparison above. Reading the new heap
counters never calls `malloc_trim`; the serving change is the startup
environment setting alone.

The throughput regression used the existing code, prose and counting fixtures,
with one warm-up and one scored repetition at each concurrency/temperature:

| Decode check (tok/s) | Code | Prose | Counting |
|---|---:|---:|---:|
| C1, greedy | 98.5 | 59.1 | 139.3 |
| C1, sampled | 100.9 | 62.3 | 135.6 |
| C32 aggregate, greedy | 309.2 | 268.8 | 378.0 |
| C32 aggregate, sampled | 267.3 | 247.2 | 364.3 |

All 24 waves and 396 requests passed. Every scored C32 wave reached full
occupancy; all 12 rates were within 2.7% of the previous three-run medians.
These single-repetition checks found no material decode regression and remain
separate from the three-repetition headline benchmark. C1 measures first-to-last
content decode; C32 uses only full-occupancy steady decode intervals.

The matched quiet endpoints retained 64 histories, 408 MiB of snapshots and
144 resident graphs. Head process anonymous memory plus swap grew 169.7 MiB,
closely matching the 169.3 MiB increase in live glibc allocations; grammar-cache
warm-up accounted for 163.6 MiB of that live growth. Free arena space rose only
0.2 MiB. The broader head container indicator rose 255.1 MiB, and the worker's
rose 1.8 MiB. The final two quiet minutes saw head process memory decrease
slightly. This supports expected cache warm-up plus a resolved allocator-retention
contributor, rather than attributing every container-accounting change to a leak.

The monitor captured 260 samples with no probe errors, OOM events, poisoned
runtimes or rank restarts. Minimum available memory was 3.06 GiB on the head
and 2.25 GiB on the worker; the unchanged 2 GiB watchdog floor remained enforced.
The server remains available on the authorized LAN endpoint, with the previous
image and stopped-state backup retained for rollback. The
[numeric follow-up receipt](../release/native-host-memory-20261011.json) preserves
both accounting views, input hashes, capacities and every throughput comparison.
This finite follow-up did not repeat the four-hour workload or start a 24-hour run.
