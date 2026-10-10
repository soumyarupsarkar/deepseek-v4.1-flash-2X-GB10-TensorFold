# Roll back the native candidate

Preserve the qualified Python checkout and image on both hosts, its immutable
assets, private configuration, ownership state and current host journals. An
asset link and a backup of ignored state are not a replacement for the current
recovery journals.

1. Stop the candidate with its own `cluster stop` and run `cluster check-host`.
   If a host is unreachable, recover that host and finish the same restoration.
2. Keep the candidate source, image, manifests and successful or failed receipts
   for diagnosis. Stop does not delete weights or images.
3. In the retained reference checkout, reverify assets if hardlink creation
   changed their metadata. For imported prepared caches, compare their content
   hashes to the preserved hashes before refreshing fingerprints. Do not weaken
   the previous controller's checks or restore stale journals.
4. Start the reference with its matching source/image/precompile records and its
   own unchanged private configuration. Confirm its health, capacity, paired
   monitor and a small synthetic request before reporting restoration complete.

## Cold-start qualification of the retained Python installation

The migration exposed a failure in the retained Python engine after the worker
rebooted. Two unchanged starts set the worker's PyTorch allocation ceiling to
about 107.1–107.2 GiB. Both failed a synthetic prefill allocation. The subsequent
peer timeout and NCCL error followed that worker allocation failure. The native
engine's paired recovery and controlled worker-reboot checks had passed.

The Python engine derives its ceiling from available host memory after warm-up.
The cold worker kept roughly 3.3 GiB of CPU anonymous memory resident, whereas
the head already had much of that state in swap. A diagnostic that requested
anonymous reclaim from the owned worker container during warm-up recovered a
109 GiB ceiling, passed baseline and structured-output checks, and restored both
hosts after stop. The configured 2.5 GiB host reserve, model, C32 capacity and KV
pool stayed unchanged. A subsequent full native → Python → native rehearsal
passed all 16 stages using the helper below, including host restoration and
serving validation. The [recovery evidence](../release/native-recovery-20261010.json)
retains the failed attempts and the separate successful rehearsal.

[`scripts/start_legacy_python.py`](../scripts/start_legacy_python.py) implements
that bounded startup procedure for the **retained source `32c4ebea` and image
`973b52de` only**. It is not a general starter or a downloadable fallback image.
Other installations should preserve their own matching source and image.

After stopping and restoring the native installation, run the helper from this
published recipe checkout, supplying the retained Python checkout. A runtime
checkout pinned to an earlier commit may not contain this later migration tool:

```bash
python3 -B scripts/start_legacy_python.py \
  --checkout /absolute/path/to/retained-python-checkout \
  --record rollback-start-01
```

The helper checks source/image identity and ownership, then makes at most one
2 GiB anonymous-reclaim request to the worker container's own cgroup before the
allocator ceiling is fixed. It checks swap availability and records all probes,
the attempted operation and resulting counters. It neither changes global
swappiness nor writes persistent memory limits. Linux may reclaim more or less
than the requested amount; this is a bounded request, not an exact byte cap.
See the [Linux 6.17 cgroup documentation](https://raw.githubusercontent.com/torvalds/linux/v6.17/Documentation/admin-guide/cgroup-v2.rst).

Reclaimed CPU pages use the existing swap device, adding startup writes. This
does not enable session caching. Stopping the container releases its memory and
swap allocations; kernel cache residency is not restored byte for byte.

The helper leaves a successful start running, but does **not** mark serving
validation complete. From the retained Python checkout, run:

```bash
python3 -B tools/qualification/qualify.py baseline --record rollback-baseline-01
python3 -B tools/qualification/qualify.py structured --record rollback-structured-01
```

Use new record names for a new attempt; never overwrite failed receipts. The
startup helper refuses insufficient allocator headroom and attempts to stop and
restore its owned pair on failure. It does not reclaim head memory, restart either host, or
retry an uncertain remote write. Preserve its private
`deployment/.local/legacy-start/<record>/` evidence and current journals if a
guard or restoration fails.

The reference remains the production fallback until the native candidate passes
feature, capacity, performance, stability and recovery gates. A passing native
build or GPU primitive test alone does not authorize a cutover claim. Never
restart a previously user-stopped endurance unit as part of rollback.
