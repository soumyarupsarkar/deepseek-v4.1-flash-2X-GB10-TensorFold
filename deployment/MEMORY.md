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

## Reading GB10 memory counters

GB10 shares system DRAM between the CPU and GPU. NVIDIA documents that
whole-device `nvidia-smi` memory totals are unsupported on this platform even
when per-process GPU usage is available. It also notes that `cudaMemGetInfo`
does not include memory that the CPU could free by moving pages to swap.
See NVIDIA's [DGX Spark memory-accounting guidance](https://docs.nvidia.com/dgx/dgx-spark/known-issues.html).

Treat these as different observations: the PyTorch allocator tracks its own
allocations, process counters describe particular mappings, and host
`MemAvailable` estimates RAM available without swapping. Flat allocator or
GPU-process counters alone cannot explain a fall in host availability, or
establish that the host-memory floor is unnecessary. The monitor continues to
use host available RAM; unused swap is not added to the 2 GiB floor.

## KV fragmentation and compaction

A separate warm-capacity test on 2026-10-09 found 31 active full-context
reservations and one queued request, with 526,336 free rows split across three
holes. The largest hole was 184,320 rows; the incoming request needed a
264,192-row aligned reservation. The server stayed healthy, but could not
admit all 32 requests together. This is distinct from the host-memory-floor
shutdown above.

When eviction alone cannot provide a contiguous reservation but aggregate
space is sufficient, the allocator now packs extents between scheduler steps.
Both ranks agree on the same layout before moving any data. Active reservations
keep their full size, retained prefixes are evicted only as needed, and existing
pool storage remains in place for captured graphs. Overlapping copies use at
most 8 MiB of temporary tensor storage at a time. Paused prefills retain their
cache objects and resume through updated views; slot rings and drafter state
do not move.

Health memory counters report `kv_compactions`, `kv_compacted_rows`,
`kv_compacted_streams`, `kv_compacted_prefills` and `kv_compaction_evictions`.
Compaction may add an admission pause. It does not increase the shared pool,
reduce a context reservation, alter model tokens or weaken the host-memory
watchdog. CPU planning, tensor-copy and allocator integration tests are covered
in `tests/publication/test_kv_compaction.py` and
`tests/test_dsv41_compaction.py`. Hardware parity, warm C32 capacity and a fresh
day-long stability run remain qualification gates for this candidate.

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
- An optional numeric native-heap snapshot from each instrumented rank,
  including its age, error counts and before/after measurements for the latest
  pressure trim. Missing reports are normal for older builds. Invalid reports
  are marked without copying their contents.

Once per minute, or when available memory falls within 1 GiB of the shutdown
floor, the collector also attempts proportional-set-size details for up to four
rank processes and four other large processes. `/proc` scans have time and count
bounds; unavailable or truncated optional measurements are marked explicitly.

The collector reads neither process command lines/environment nor inference
prompts, replies or token IDs. Process names and machine-local identifiers are
still operational data: keep these receipts private.

While running, the watchdog reuses one SSH connection through a private
temporary control socket. This avoids creating a new worker login for every
Docker or memory poll, which can repeatedly activate login and desktop-service
callbacks. Host-key checking and command timeouts remain enabled. The socket
is closed on normal exit; an orphaned master expires after 30 idle seconds.
No SSH configuration file is changed. The probe source travels through standard
input so the full program is not repeated in sudo's command log. If the private
socket directory cannot be created, polling continues with ordinary SSH.

Files live under the installation's ignored `deployment/.local/memory/`:

- `samples.jsonl` plus seven rotations: up to 32 MiB of frequent samples.
- `minutes.jsonl` plus seven rotations: up to 32 MiB of minute samples.
- Each file is at most 4 MiB; rotation retains the newest observations.

On a fault, `deployment/.local/fault.json` records the exact observed memory,
the last successful head-health sample and its age when available, and up to
twelve recent watchdog observations before normal paired stop/restoration.
History-write failures cannot suppress that shutdown. The monitor does not
automatically restart a faulted pair.

## Native-heap pressure experiment

A later instrumented run reproduced a head-memory-floor shutdown after about
2 hours 49 minutes. The head inference process's anonymous-plus-swap footprint
grew by about 2.13 GiB while the measured GPU reservation stayed flat. Both ranks
stopped normally and host restoration passed. This locates the measured growth
in the rank process, but does not yet distinguish live native allocations from
freed pages retained by an allocator. The failed run is not an endurance pass.

The candidate profile enables `TF_DS_HOST_MEMORY_STATS=1` and
`TF_DS_HOST_TRIM_GIB=3.5`. A CPU-only daemon on each rank samples glibc
`mallinfo2`, process anonymous/swap counters and host `MemAvailable` every five
seconds. Below the trim threshold it calls `malloc_trim(0)` and records before
and after counters. It does not collect Python garbage, call CUDA, resize KV
storage or free live allocations. The 2 GiB paired watchdog remains unchanged.
The [glibc allocator statistics](https://sourceware.org/glibc/manual/latest/html_node/Statistics-of-Malloc.html)
describe native arenas and free/in-use space; they do not account for all memory
in a process. Trimming can cost CPU time, and its return value does not quantify
reclaimed bytes. Concurrent allocations make available-memory deltas approximate.

Each rank atomically replaces one private, bounded numeric report at
`/tmp/tensorfold-host-memory.json`. The host watchdog accepts only known numeric
fields from a regular file up to 8 KiB; the usual bounded rings preserve the
observations. No request data, environment or command-line arguments enter this
report. Sampling/write failures are counted without exposing exception messages
and cannot disable the paired watchdog. This change has no persistent host
setting. Full-model reclaim and fresh endurance validation remain outstanding.

For rollback, stop the pair, set `TF_DS_HOST_TRIM_GIB` to `0` in the selected
profile, commit and rebuild/restart through the normal controller. Keeping
`TF_DS_HOST_MEMORY_STATS=1` retains measurement alone; setting both options to
`0` disables the daemon. Alternatively select the previous pinned source and
matching image using [ROLLBACK.md](ROLLBACK.md). Do not lower the watchdog floor
to compensate for an ineffective trim.

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
