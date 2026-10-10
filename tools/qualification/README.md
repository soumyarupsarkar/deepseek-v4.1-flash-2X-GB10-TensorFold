# Native qualification clients

These clients send deterministic synthetic fixtures to an already running,
otherwise idle candidate. They are not installation or startup commands. Use
a dedicated loopback-bound installation with its matching image and private
state; the native adapters refuse a LAN-bound configuration. They neither read
ordinary inference traffic nor reuse user prompts.

Receipts are private under `deployment/.local/qualification/records/`; benchmark
receipts are under `deployment/.local/records/`. Choose a new `--record` for
every attempt. Preserve failures and interruptions. Publish only reviewed
aggregate evidence, not raw host state or service logs.

## Feature gates

Run these separately, stopping after any failure:

```bash
python3 -B tools/qualification/native_features.py baseline --record native-baseline-01
python3 -B tools/qualification/native_features.py structured --record native-structured-01
python3 -B tools/qualification/native_features.py sampling --record native-sampling-01
python3 -B tools/qualification/native_features.py aliases --record native-aliases-01
python3 -B tools/qualification/native_features.py protocols --record native-protocols-01
```

The baseline checks arithmetic, drafted/ordinary greedy parity, two synthetic
PNG colors, prefix reuse and four concurrent replies. Structured tests cover
JSON objects, strict schemas, streamed JSON, named/automatic/required tools,
thinking budgets, mixed traffic and invalid schemas. Sampling tests cover
fresh seeds, explicit zero, returned-seed replay, streaming and concurrency.
Alias tests check the four exact context limits and over-limit refusals.
Protocol tests cover Chat, Responses and Anthropic Messages.

## Capacity, replay and compaction

These workloads are more expensive and belong on the isolated pair:

```bash
python3 -B tools/qualification/native_parity.py --record native-parity-greedy-01
python3 -B tools/qualification/native_parity.py --temperature 1 --record native-parity-sampled-01
python3 -B tools/qualification/native_retention.py --record native-retention-01
python3 -B tools/qualification/native_qualification.py pool --streams 32 --prompt-tokens 2048 --reply-tokens 1024 --check-solo --record native-pool-01
python3 -B tools/qualification/native_qualification.py memory --streams 32 --rounds 2 --initial-tokens 261120 --growth 0 --reply-tokens 1024 --shared-prefix --identical --require-concurrency --require-replay-parity --record native-c32-full-01
python3 -B tools/qualification/native_compaction.py --record native-compaction-01
python3 -B tools/qualification/native_context.py --tokens 1048576 --reply-tokens 256 --mixed --record native-million-01
```

The parity client compares ordinary and drafted token hashes at C4/8/16/24/32,
with matching prompt hashes and explicit seeds. A mode labeled drafted must
actually exercise drafting. Retention tests cold, replayed and extended
prefixes, including the retained-state bound.

The full C32 test primes one identical document and creates independent active
session state. It does not claim 32 cold independent document prefills. The
compaction client reserves large extents with short prompts, fragments the
live reservations, requires actual relocation, then compares continued output
with solo execution. It tests relocation correctness, not long-context speed.
The million-token fixture places three passphrases across synthetic filler and
requires retrieval while checking the total prompt-plus-reply boundary.

## Recovery and endurance

```bash
python3 -B tools/qualification/native_qualification.py recovery --record native-recovery-01
python3 -B tools/qualification/native_qualification.py soak --streams 32 --seconds 360 --record native-short-soak-01
```

Cancellation and protocol recovery do not replace paired host-failure and
restoration tests. A six-minute soak does not establish day-long stability.
The migration's separately scheduled 24-hour run must use a new unit/record,
stop on faults, include quiet windows and retain bounded evidence. Never
restart a user-stopped endurance unit as a shortcut.

## Performance

Use `deployment/scripts/benchmark.py` with an explicit JSON suite. Its native
health adapter measures live committed tokens, preserves the original native
counters and errors on missing counters. It does not invent Python allocation
or sealed-graph counters. Cold waves evict retained prefixes and require zero
reported cached tokens in every scored reply. Native graph captures during a
wave are recorded; they are not silently removed from timings.

Compare concurrency, exact prompt/output budgets, prompt hashes, model/overlay,
sampling, cache state, repetitions and image identities. End-to-end throughput
includes prefill and admission. Steady decode requires a sufficiently long
sampled interval with all requested streams decoding and none queued. A short
or unobserved steady interval is null, not a guessed rate.

`qualify_*.py` files also contain the retained Python fixture implementations.
Invoke the `native_*.py` adapters above for native serving; a historical Python
receipt or an unchanged fixture is not itself native qualification.
