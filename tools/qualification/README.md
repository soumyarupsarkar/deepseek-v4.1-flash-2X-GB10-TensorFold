# Paired acceptance workloads

Run these on an otherwise idle, running installation after `cluster start`.
They use the saved local configuration and synthetic fixtures, generated color
images, or the unchanged public upstream benchmark corpus. They never read
ordinary inference request logs or select/restart the serving profile.

```bash
python3 -B tools/qualification/qualify_capacity.py --phase draft-tuning --record acceptance
python3 -B tools/qualification/qualify_retention.py --record acceptance-retention
python3 -B tools/qualification/qualify_loop_guard.py --record acceptance-loop-guard
```

The first command checks text and vision, strict schemas/tools, random seeding
and explicit replay, ordinary/drafted token parity, two waves of 32 simultaneous
262,144-token sessions, native-million retrieval, queue/cancel recovery and a
mixed-request soak. The large C32 workload primes an identical document; it
does not measure 32 independent cold document prefills. Allow several hours.
The retention command checks 32 distinct cached prefixes, sequential reuse,
continuation equality and LRU eviction.

For a warm-pool compaction regression check, run identical full-context waves
after mixed retention/schema traffic:

```bash
python3 -B tools/qualification/qualify_memory.py --record warm-compaction \
  --streams 32 --rounds 2 --initial-tokens 261120 --growth 0 --reply-tokens 1024 \
  --shared-prefix --identical --require-concurrency --require-replay-parity \
  --require-compaction
```

This requires 32 simultaneous decoders in each wave, identical output token
hashes for each fixed seed across the two waves, and at least one compaction.
If the starting layout needs no compaction, the command fails that coverage
gate; it does not silently claim to have tested relocation. Receipts retain
hashes rather than full output token lists. Cold prefills of 32 independent
documents and compaction performance require separate measurements.

The loop-guard smoke checks ordinary non-looping replies, streaming, concurrent
requests and exclusions for schemas/thinking budgets. Deterministic forced-loop
and continuation-seed checks use synthetic HTTP engines in
`tests/test_cuda_loop_guard.py`; they do not reuse real inference traffic.

For CPU-grammar pressure, a separate probe creates distinct strict JSON schemas
and tool sets, checks short constant answers, then replays its first wave:

```bash
# Offline fixture summary; sends no inference or host commands.
python3 -B tools/qualification/qualify_schema_churn.py --describe --streams 4 --tools 8
# Run only on an otherwise idle installation, between other acceptance jobs.
python3 -B tools/qualification/qualify_schema_churn.py --record schemas-c4 --streams 4 --tools 8
```

Increase `--streams` (up to 32), `--tools` (up to 64) and `--rounds` deliberately.
`--variant-base` offsets fixture names/constants so repeated runs can exercise
fresh compilation; the default is zero. `--mode tools` or `--mode json` isolates
one compiler instead of the default mixed workload. Receipts verify the pair's
identity, answers, sealed graph count and unchanged allocation-error counters.
They keep at most 4,096 scalar health/memory observations, with the total sample
count reported separately. This probe does not establish endurance, throughput,
or full-context capacity by itself.

Each command creates receipts under Git-ignored
`deployment/.local/qualification/records/`. Use a different `--record` prefix
for another run. Preserve failures and slow runs. Receipts contain installation
identifiers and responses to the synthetic probes; review and summarize them
before publishing. Performance claims require the separate benchmark clients
and their documented timing boundaries.

Set `DEEPSEEK_CLUSTER_CONFIG` to use a different local configuration path.
The controller's normal configuration-ownership checks still apply. These
clients place substantial load on both GPUs and can exercise the watchdog;
run them during a maintenance window. They do not perform the separate
worker-failure, interrupted-start or host-restoration acceptance checks.

## Lifecycle fault tests

These explicit maintenance operations each leave both ranks stopped and check
restoration against this installation's baseline. They preserve models/images.

```bash
# Start with both hosts idle and the pair stopped.
python3 -B tools/qualification/check_lifecycle.py interrupted-start --record interrupted
python3 -B cluster start
# Run inference/capacity acceptance, then wait until all requests have finished.
python3 -B tools/qualification/check_lifecycle.py worker-failure --record worker-loss
python3 -B cluster start
```

The first terminates a setup child after writing both display journals, then
uses normal paired stop to recover. The second deliberately kills only the
owned idle worker and waits for the real paired monitor to clean up and restore
both hosts. A failed fault test retains its receipt; use normal `cluster stop`
and `check-host` for recovery before investigating. Neither test reboots a host.
