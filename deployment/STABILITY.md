# Four-hour native stability observation

The initial diagnostic runs the current serving image for four hours, then
finishes with a matched quiet-memory observation. It preserves the running
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
  --diagnostic-prerequisites release/native-throughput-policy-20261010.json \
  --record native-four-hour-UNIQUE \
  --hours 4
```

Choose a fresh record name. Evidence lives in the serving checkout under
`deployment/.local/qualification/endurance/<record>/`:

- `status.json`: phase, progress, source/image, target finish, final memory summary.
- `cycles.jsonl`: mixed/deep results, replay checks and detailed quiet endpoints.
- `memory.jsonl`: bounded numeric samples copied from the watchdog.

For an unattended run, use a transient systemd service with `Restart=no`,
`RuntimeMaxSec=4h20m` and `TimeoutStopSec=30s`, running as the deployment user.
The extra service allowance covers an in-flight wave and final quiet sampling;
it does not start a second test or extend the four-hour workload schedule.
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

## Initial result and memory investigation

The October 11, 2026 run completed 107 mixed C32 waves, 22 cold deep-context
waves (including four million-token requests), and 109 matching fixed-seed
canaries. There were no correctness failures, poisoned runtimes, OOM events or
rank restarts. Including final normalization and quiet sampling, it took
4 hours 4 minutes 42 seconds. This was the requested four-hour observation,
not the separate 24-hour endurance qualification.

Across matched quiet endpoints, the head container's anonymous memory plus
swap increased by 539 MiB; the worker increased by 21 MiB. The grammar cache
grew by 170 MiB during warm-up, but head growth continued after it levelled
off. Snapshot residency stayed at 64 states / 408 MiB. Graph residency stayed
within its 144-executable limit.

Component controls separated ordinary request handling from grammar churn:
2,000 health requests, 256 tokenization requests and 256 plain C32 inference
requests showed little head growth. Repeating one schema was also stable after
warm-up. Cycling through 128 schemas then added about 113 MiB with essentially
unchanged grammar-cache size and unchanged graph residency. In a disposable
CPU-only process using the same pinned grammar library and tokenizer, live
glibc allocations plateaued while freed arena space grew; an explicit trim
returned about 82 MiB. This establishes allocator retention as a contributor;
the grammar-cache byte counter alone does not describe total host memory.

The profile now fixes glibc's automatic trim threshold at 128 KiB. The isolated
repeat control with that setting stayed near 252 MiB of anonymous memory plus
swap after warm-up, versus growth to about 310 MiB with defaults. Compiled cache
contents remained available. Serving validation and its exact scope are recorded
with the follow-up receipt; this CPU result alone does not establish serving
performance or indefinite stability.

The CPU control is reproducible with
[`native_grammar_heap.py`](../tools/qualification/native_grammar_heap.py). Run it
in a disposable instance of the pinned serving image with no GPU access, a
read-only `/model` mount and a memory limit. It never contacts the inference
server. Compare a default process with one launched using
`MALLOC_TRIM_THRESHOLD_=131072`; `--trim-at-end` optionally measures how much
this disposable process can return after its repeated work. Output contains
only synthetic-test metadata, input hashes and numeric memory/cache samples.
