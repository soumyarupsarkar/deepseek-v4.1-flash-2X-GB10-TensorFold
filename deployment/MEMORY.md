# Native memory, admission and paired shutdown

The profile configures a shared **8,650,752-token logical KV pool**, **32 active slots** and an independent **1,048,576-token request ceiling**. These are three separate constraints. Active and retained histories share the pool. A slot count is not a guarantee that every slot can hold the largest allowed request simultaneously.

## Resident memory and host reserve

KV buffers, weights, attention scratch, drafter workspace, RDMA buffers, retained checkpoints, graph executables and host allocations all consume the two GB10s' unified memory. Logical pool tokens do not describe total resident bytes or populated history. Use the selected image's measurements and the host counters together.

The profile asks the engine to leave 2.5 GiB of host reserve and the paired monitor uses a 2 GiB `MemAvailable` floor. This reserve is an allocation budget, not RAM protected from unrelated processes. Startup additionally requires 112 GiB available before model loading. Do not lower the floor simply to hide a failure.

The DRM allocator reserves 1,792 MiB of display memory and places eligible whole KV tensors there with alignment. Hot scratch and other tensors use the ordinary CUDA allocator. The controller journals the current-boot display/module changes before making them and restores them on stop. No inference service is enabled at boot.

CUDA allocation counters are not a complete host-memory measurement. Compare `MemAvailable`, swap, pressure and process RSS/private/PSS data as well. A low CUDA allocation count does not rule out host pressure, driver allocations, page cache or another process. The previous Python allocator investigation is historical and does not establish native stability.

## Admission, retained prefixes and compaction

A request reserves space for prompt plus allowed reply. Requests can wait for enough contiguous pool space even when a slot is available. The aliases change the request ceiling, not the pool size or model weights.

The native implementation bounds retained checkpoint states at 64 and their snapshot budget at 512 MiB. Retained states are not additional active slots and their KV extents remain part of the shared pool. Eviction releases reusable history when admission needs the space.

When free space is fragmented, the native allocator can pack live reservations to the left using aligned, non-overlapping CUDA copies, synchronize relocation with the follower, update bases and invalidate stale snapshots. Qualification must demonstrate both an actual relocation and unchanged continuing output; a pure allocation-plan unit test is insufficient.

Target-round graphs are captured lazily for bounded shapes. The deployment
profile retains at most 144 executables, enough for all 48 row widths and three stretches in one
context bucket. A new shape evicts the least recently used executable and is
captured normally. The engine's default limit remains 512; the profile explicitly
selects the smaller bound. Alternating between many contexts and row shapes can
therefore add recapture latency. This bounds executable residency, not total
physical driver memory, and does not change the KV pool or retention budget.

Benchmark wall time includes captures and recaptures. Cost calibration excludes
capture rounds using the cumulative capture counter, since resident occupancy
can stay constant during replacement. Eager fallback remains available for a
sealed cache; the deployment does not select sealed operation. The
[drafting investigation](../benchmarks/NATIVE-DRAFTING.md) records the image-specific
hardware checks and observed memory limits.

## Read the native counters

`/health` exposes real native counters; missing Python counters must not be treated as zero:

| Field | Meaning |
|---|---|
| `native.pool_tokens`, `context_tokens`, `stream_slots` | Configured independent capacities |
| `native.active_streams`, `prefilling_streams` | Current workload occupancy |
| `native.prefill_tokens`, `verify_rounds`, `draft_passes` | Monotonic engine progress |
| `native.retained_states`, `snapshot_bytes` | Retained checkpoint count and bytes |
| `native.compactions`, `relocated_tokens` | Executed live relocations |
| `native.round_graphs`, `graph_limit` | Resident target-round graph executables and their configured limit |
| `native.graph_captures`, `graph_evictions`, `graph_eager_fallbacks` | Cumulative captures (including recaptures), replacements and eager fallbacks |
| `native.drm_reserved_bytes`, `drm_used_bytes` | Display-memory allocator budget and placement |
| `native.rdma_failed`, `runtime_poisoned` | Failure state requiring coordinated recovery |
| `scheduler.generation_tokens_total` | Committed outputs, including currently active requests |

`runtime_poisoned` is a top-level field. Once poisoned, the native server returns unhealthy status; neither rank can safely continue alone.

## Bounded private evidence and recovery

The paired monitor stores only allowlisted numeric health/host evidence. It does not collect prompts, replies, process argument lists or environment variables. Two rotating series retain at most 64 MiB on disk, plus a small in-memory window. They are operational writes, not NVMe session KV caching.

On a repeated health/memory failure or stalled progress, the monitor captures bounded diagnostics and stops the owned pair. Rank communication has its own timeout; an uncertain exchange poisons the runtime. The monitor does not automatically restart either rank.

Preserve the fault receipt, both rank logs and memory history before diagnosis. Logs can contain private information and must not be published wholesale. Stop and check host restoration through the same installation's controller, resolve the concrete fault, and restart both ranks together only when appropriate. [Rollback](ROLLBACK.md) retains source, images, assets and the recovery journals.

Short smoke tests establish neither full C32 capacity nor day-long stability. Native capacity, performance, quiet-window growth and endurance receipts are separate gates in [the migration plan](../MIGRATION.md).

The [four-hour stability observation](STABILITY.md) provides an initial mixed-load
run with matched quiet windows and per-run memory history on the serving image.
