# Paired acceptance workloads

Run these on an otherwise idle, running installation after `cluster start`.
They use the saved local configuration and synthetic fixtures, generated color
images, or the unchanged public upstream benchmark corpus. They never read
ordinary inference request logs or select/restart the serving profile.

```bash
python3 -B tools/qualification/qualify_capacity.py --phase draft-tuning --record acceptance
python3 -B tools/qualification/qualify_retention.py --record acceptance-retention
```

The first command checks text and vision, strict schemas/tools, random seeding
and explicit replay, ordinary/drafted token parity, two waves of 32 simultaneous
262,144-token sessions, native-million retrieval, queue/cancel recovery and a
mixed-request soak. The large C32 workload primes an identical document; it
does not measure 32 independent cold document prefills. Allow several hours.
The retention command checks 32 distinct cached prefixes, sequential reuse,
continuation equality and LRU eviction.

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
