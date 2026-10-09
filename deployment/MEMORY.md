# Memory pressure and paired shutdown

The selected profile shares 8,650,752 logical KV tokens across 32 slots, with a
1,048,576-token per-request limit. The 109 GiB PyTorch allocator upper bound and
2.5 GiB startup host floor do not bound all memory used by CUDA, Python, the
driver or unrelated host processes. The paired monitor retains its **2 GiB
available-host-memory floor** and two-consecutive-failure policy.

A deployment crossed the worker's floor after approximately 22 hours on
2026-10-09. Both rank containers were still running before the monitor stopped
them. The original fault receipt recorded a reason but no memory measurements;
that receipt alone cannot distinguish a leak, an allocation peak or host
background pressure. The new diagnostics address that evidence gap. They are
not a claim that the cause has been fixed or that a long stability run passed.

## Evidence collected by the monitor

Each normal watchdog cycle records, on both machines:

- Available RAM, anonymous/file/shared memory, slab, swap, kernel/page-table
  memory, memory-pressure counters and cumulative swap/OOM counters.
- The twelve largest processes by RSS, and up to 32 processes descended from
  the owned rank's container init PID, identified by PID and start time.
- Cgroup memory counters when available. RSS sums include shared mappings and
  must not be read as additional physical-memory consumption.
- A scalar-only view of the head API's allocation, KV, retained-prefix,
  concurrency and scheduler counters. This API does not expose the worker's
  PyTorch allocator counters; the worker's host/process counters are separate.

Once per minute, or when available memory falls within 1 GiB of the shutdown
floor, the collector also attempts proportional-set-size details for up to four
rank processes and four other large processes. `/proc` scans have time and count
bounds; unavailable or truncated optional measurements are marked explicitly.

The collector reads neither process command lines/environment nor inference
prompts, replies or token IDs. Process names and machine-local identifiers are
still operational data: keep these receipts private.

Files live under the installation's ignored `deployment/.local/memory/`:

- `samples.jsonl` plus seven rotations: up to 32 MiB of frequent samples.
- `minutes.jsonl` plus seven rotations: up to 32 MiB of minute samples.
- Each file is at most 4 MiB; rotation retains the newest observations.

On a fault, `deployment/.local/fault.json` records the exact observed memory,
the last successful head-health sample and its age when available, and up to
twelve recent watchdog observations before normal paired stop/restoration.
History-write failures cannot suppress that shutdown. The monitor does not
automatically restart a faulted pair.

## Investigation and recovery

Preserve the fault, rank logs, stop records and memory history before starting
another investigation. Compare low-memory samples with a fresh idle baseline,
then exercise repeated session creation, continuation, cancellation and idle
periods. Host availability, proportional process memory and allocator counters
measure different things; use their changes together to locate the pressure.
Keep failed and slow runs, and check whether memory plateaus after warm-up or
continues growing across equivalent cycles.

Use the installation's normal controller to stop and verify restoration:

```bash
python3 -B cluster --config deployment/.local/installed.json stop
python3 -B cluster --config deployment/.local/installed.json check-host
```

After resolving the pressure, restart the selected pinned build and qualify it
under both busy and idle conditions. A short successful restart is not evidence
of day-long stability. [Rollback](ROLLBACK.md) preserves source, images, models,
host baselines and journals; selecting an older image also requires its matching
clean source checkout. The memory recorder needs no host package or persistent
system configuration, and exits with the paired monitor.
