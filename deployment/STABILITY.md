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
