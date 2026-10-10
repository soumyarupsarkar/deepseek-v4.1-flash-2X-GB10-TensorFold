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
python3 -B tools/qualification/native_prefill.py --latency-limit 30 --record native-prefill-01
python3 -B tools/qualification/native_features.py structured --record native-structured-01
python3 -B tools/qualification/native_features.py sampling --record native-sampling-01
python3 -B tools/qualification/native_features.py aliases --record native-aliases-01
python3 -B tools/qualification/native_features.py protocols --record native-protocols-01
python3 -B tools/qualification/native_image_formats.py --record native-image-formats-01
```

The baseline checks arithmetic, drafted/ordinary greedy parity, two synthetic
PNG colors, prefix reuse and four concurrent replies. Structured tests cover
JSON objects, strict schemas, streamed JSON, named/automatic/required tools,
thinking budgets, mixed traffic and invalid schemas. Sampling tests cover
fresh seeds, explicit zero, returned-seed replay, streaming and concurrency.
Alias tests check the four exact context limits and over-limit refusals.
Protocol tests cover Chat, Responses and Anthropic Messages.
The incremental-prefill client requires small text, schema and image requests to
finish during a long prompt within 30 seconds, checks output against solo
execution, and exercises cancellation while a prompt is still being filled.
The image-format client uses generated colored squares to exercise JPEG and
WebP through all three APIs and requires a malformed image to return HTTP 400.
It needs no client-side image libraries; the encoded fixtures are included.

## Capacity, replay and compaction

These workloads are more expensive and belong on the isolated pair:

```bash
python3 -B tools/qualification/native_parity.py --record native-parity-greedy-01
python3 -B tools/qualification/native_parity.py --temperature 1 --record native-parity-sampled-01
python3 -B tools/qualification/native_constraints.py --record native-constraints-01
python3 -B tools/qualification/native_constraints.py --temperature 1 --record native-constraints-sampled-01
python3 -B tools/qualification/native_retention.py --record native-retention-01
python3 -B tools/qualification/native_qualification.py pool --streams 32 --prompt-tokens 2048 --reply-tokens 1024 --check-solo --record native-pool-01
python3 -B tools/qualification/native_qualification.py memory --streams 32 --rounds 2 --initial-tokens 261120 --growth 0 --reply-tokens 1024 --shared-prefix --identical --require-concurrency --require-replay-parity --record native-c32-full-01
python3 -B tools/qualification/native_compaction.py --partial-prefill --record native-partial-compaction-01
python3 -B tools/qualification/native_decode_compaction.py --record native-decode-compaction-01
python3 -B tools/qualification/native_context.py --tokens 1048576 --reply-tokens 256 --mixed --require-interleaving --small-latency-limit 30 --record native-million-01
```

The parity client compares ordinary and drafted token hashes at C4/8/16/24/32,
with matching prompt hashes and explicit seeds. A mode labeled drafted must
actually exercise drafting. Retention tests cold, replayed and extended
prefixes, including the retained-state bound.
The constrained C32 client uses distinct per-request schemas and required tool
calls, checks every result, and requires all 32 requests to overlap in decoding.
It verifies grammar isolation and masked ordinary decoding, not drafted strict
output: constrained requests intentionally disable drafting.

The full C32 test primes one identical document and creates independent active
session state. It does not claim 32 cold independent document prefills. The
partial-prefill compaction client reserves large extents, fragments the live
reservations, and requires a populated partial prompt to move before it
emits its first reply token. Before comparing the resulting output with solo
execution, it displaces retained checkpoints and requires the solo requests to
report zero cached tokens. A separate decoder-compaction client selects a
witness set guaranteed to contain a moved reservation, takes a generated-token
checkpoint after the move, and requires continued text beyond that checkpoint
to match solo output.
Reading buffered text generated before relocation cannot alone satisfy that
check. These are relocation correctness tests, not long-context speed claims.
The million-token fixture places three passphrases across synthetic filler and
requires retrieval at the total prompt-plus-reply boundary. Its small requests
must also complete during prefill and within the declared latency limit.

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

`native_endurance.py` implements the new run. It requires an explicit gate
manifest before sending traffic: `status: "passed"`, an exact `source` Git
revision and `image` digest, the complete `passed` set (`features`, `parity`,
`retention`, `compaction`, `capacity`, `million`, `prefill-responsiveness`,
`recovery`, `matched-benefit`),
and preserved `receipts` with `path` and `sha256`. Build that manifest only
after reviewing the actual results. It is an evidence binding, not a substitute
for those tests or their interpretation.

```bash
python3 -B tools/qualification/native_endurance.py --record native-endurance-01 --gates /path/to/private/passed-gates.json --hours 24
```

Schedule it in a new bounded service when unattended execution is needed. The
harness mixes 32 synthetic requests, strict output, tools and images; checks
fixed-seed replay; rotates deep-context waves; and takes hourly quiet samples.
Its append-only evidence is capped at 64 MiB and excludes reply text. Exceeding
the cap fails the run while preserving earlier records. On a fault it attempts
to stop the original owned pair; it refuses to stop a replacement launch.
Interruption remains interruption, not a passing endurance result. The
`cycle_requests` count covers ordinary mixed cycles and their replay canaries;
deep waves, eviction fixtures and initial/final canaries are recorded separately.

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

`scripts/compare_native.py` checks two completed benchmark receipts for exact
case and prompt-hash agreement, completed output budgets, and actual cold-cache
behavior. Every declared scored case must have a completed wave, and each wave
must contain every stream index exactly once. Matching subsets of incomplete
suites cannot establish a complete comparison. It emits aggregate timing fields,
image/receipt digests and an output hash-match count, without private launch
configuration or response text:

```bash
python3 -B scripts/compare_native.py /path/to/python-receipt.json /path/to/native-receipt.json --output /path/to/new-comparison.json
```

Missing steady measurements stay missing, including when only one repetition
has a usable interval. Review the individual repetitions and timing spread;
the comparison does not decide whether a deployment should be cut over.

`qualify_*.py` files also contain the retained Python fixture implementations.
Invoke the `native_*.py` adapters above for native serving; a historical Python
receipt or an unchanged fixture is not itself native qualification.
