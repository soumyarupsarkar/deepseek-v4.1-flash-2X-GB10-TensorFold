# Native release status

## Current: October 25 upstream correctness update with stock Mia

Runtime `1163c7ce79aee5b523cff5130790937c4be0ea51`, image
`sha256:369b10a3d8872375879a46b17399a0fa523469fd1f3480215b0bc603d8761739`,
passed isolated qualification and is serving on the LAN. The model and
optional Keys pins are unchanged: stock Mia EAQ v1 remains selected, with
32 active slots, 8,650,752 shared logical KV tokens and a 1,048,576-token
request ceiling. Aliases, vision, structured outputs and random seeds remain.

The update incorporates malformed DSML envelope handling, streamed tool-call
parsing and accompanying prose, UTF-8 bounds checks, prompt-change Engram
read-ahead invalidation, AIO index validation, template append allocation,
optional Anthropic thinking budgets and the missing 512/513-token top-k kernel.
[Changes, upstream attribution and deferred updates](../deployment/UPSTREAM-20261025.md).

- The build passed 374 native tests and one C++ grammar test; publication and
  controller suites passed 115 Python tests. Both hosts passed nine GPU checks,
  complete stock tensor-byte comparison and all 78 optional Keys slice checks.
- All 17 finite stock gates passed on uninterrupted rank processes, including
  greedy/sampled drafting parity through C32, vision and protocols, retention,
  prefill/cancellation, compaction, full-window C32 replay and million-token
  retrieval. Exact 511/512/513/514-token boundary cases also passed.
- Both C32 waves decoded 32 sessions of 261,120 input + 1,024 output tokens,
  with exact replay. They use a shared primed document with independent active
  reservations, rather than 32 unrelated cold prefills. The cold million-token
  request recovered all three passphrases and generated 256 output tokens.
- A short matched greedy diagnostic produced 198 identical replies and token
  counts across retained and updated runtimes. C32 throughput changed by
  −3.08% to +0.66% across code, prose and counting. Its one scored repetition
  per shape is a regression screen, separate from the repeated headline campaign.
- Stock → Keys → stock preserved aliases and exact stock replay. Keys passed
  baseline and structured-output checks and added zero resident weight bytes.
- Across about 56 minutes, 632 memory samples recorded no monitor failures;
  minimum available RAM was 2.45 GiB on the head and 3.73 GiB on the worker.
  The 2 GiB stop threshold is unchanged. No new 12/24-hour endurance claim is made.
- The separate LAN installation repeated both hosts' preparation and complete
  tensor comparisons. All twelve fresh synthetic requests passed, including
  aliases, strict output, tools, vision, random seeds/replay and streaming.
  Both ranks reported stock; worker-to-head LAN reachability and the paired
  monitor passed. The serving checkout stays pinned to the tested runtime;
  later documentation commits do not rebuild or replace it.

[Numeric qualification evidence](native-upstream-20261025.json) ·
[Matched diagnostic and rollback](../deployment/UPSTREAM-20261025.md#qualification-and-rollback).
The prior source, image, assets and restoration journals are retained. Creating
the new installation's hardlinks changes inode ctime; revalidate the retained
owner's assets and prepared caches before rollback startup. No weight redownload
or reboot is required while those retained assets remain intact.

## Previous: initial Mia EAQ 1017 qualification with optional matching Keys

The initial Mia deployment used **stock Mia-AiLab EAQ v1 2.9-bpw 1017 weights**.
The matching Keys K5 sidecar is prepared and selectable, but off. It retains
32 active slots, 8,650,752 shared logical KV tokens, a 1,048,576-token request
ceiling, the same aliases, vision, structured output and random request seeds.

Measured runtime source: `7ebfbdbf3b01da8ab56a4d995324205104082efa`. Both hosts used image
`sha256:304b45701d11c6e852d26984990a6105c64473cef56eb148d9aa5e96dfe1eb87`.
That tested runtime remains retained for rollback.

- Every prepared stock tensor byte and every overlay slice passed comparison
  on both ranks, and all nine GPU preparation checks passed per host. The
  container build passed 328 native CPU/server and one C++ grammar test.
- Both variants passed all 21 finite gates, full-window C32 exact replay and
  cold million-token retrieval. Successful five-stage switching ended stock,
  with exact within-variant replay and unchanged aliases/base caches.
- All three matched campaigns retain 48 waves / 792 requests each. Mia stock's
  six C32 medians improved 0.10–2.57% versus the fresh LibertAI baseline. C1
  sampled code slowed 6.22%; other results and all repetitions remain visible.
- Loaded stock weights use 79.97 MiB less per rank. The matching Keys overlay
  adds zero resident GPU weight bytes; pool size and guard floors are unchanged.
- The one-hour stock and half-hour Keys diagnostics passed workload and memory
  review. These are bounded observations, not 12/24-hour endurance qualification.
  A separate new LAN startup passed all twelve synthetic requests, both-rank
  stock checks and remote reachability.

| Variant | Observed duration, including final normalization and quiet window | Mixed cycles | Cold deep-context requests | Total requests |
| --- | ---: | ---: | ---: | ---: |
| Mia stock | 65.1 min | 28 | 5 | 1,379 |
| Mia keys | 34.6 min | 25 | 2 | 1,085 |

| Variant | Host | Lowest sampled available RAM across validation | Quiet-window rank anonymous + swap change |
| --- | --- | ---: | ---: |
| Mia stock | head | 2.589 GiB | +2.29 MiB |
| Mia stock | worker | 2.183 GiB | +2.15 MiB |
| Mia keys | head | 2.706 GiB | +2.57 MiB |
| Mia keys | worker | 3.724 GiB | +2.03 MiB |

No OOM increments, poisoned/RDMA runtime, rank restarts or monitor failures
were observed. The memory deltas use normalized retained caches and at least
two quiet minutes; host available RAM is not a direct GPU allocation measure.
The earliest approximately 35 minutes of stock use the retained minute-series
observations after older high-resolution files rotated out; later stock and
all Keys retain roughly five-second observations. Sampling coverage and file
hashes are explicit in the numeric report.

[Numeric release evidence](native-mia-1017-20261020.json) ·
[Current workload measurements](../benchmarks/NATIVE-WORKLOADS.md) ·
[LibertAI/Mia comparison](../benchmarks/MIA-1017-COMPARISON.md) ·
[Stock/Keys comparison](../benchmarks/KEYS-1017-COMPARISON.md) ·
[Setup and reversible migration](../deployment/MIA-1017.md).

The previous source, images, installation journals and prepared caches remain
retained. Reclaimed worker source files have verified head-side backups;
restoring the previous deployment requires copy-back and content verification.
That full copy-back has not been rehearsed. No model-quality ranking, refusal
rate or long-term leak-freedom claim follows from this qualification.

## Previous: LibertAIDAI 1017 with optional Keys mixed precision

The previous deployment used the **stock** LibertAIDAI 1017 2.9 bpw pack.
The separately qualified optional Keys variant adds drowzeys' pinned 1017 K6
attention replacements in layers 10–35. Both variants share immutable base downloads and prepared
stock caches, expose identical model IDs and retain 32 slots with an
8,650,752-token pool. [Setup, switching and rollback](../deployment/KEYS-LIBERT-1017.md).

Runtime source `9f8d14e349be3811147b1fd5b35bcbdac6f824fd`, image
`sha256:eedc8c3acc3109262c92ccb4fcd8221b115f992cc34f644acd1bc40034c1a84a`. Later documentation and evidence commits do not change
this measured image. [Numeric qualification report](native-keys-1017-20261018.json).

The build passed 327 native tests and the C++ grammar check. Both hosts passed
nine preparation checks, every stock prepared-tensor byte comparison, and all
78 Keys slice comparisons. Only the selected tensors are uploaded; the measured
resident-weight increase is **65 MiB per GPU**, without a second full cache.

Initial Keys qualification found a host-memory guard stop during full-C32
raw-token request admission. Parsed JSON trees were retained throughout each
reply; the head's anonymous memory rose by about 373 MiB. The replacement
runtime releases parsing scratch after making an owned, compact request plan.
Two native regressions check data ownership and a full-window plan below
2 MiB. The complete finite suite below was repeated on the replacement image,
including the failing workload, with the KV capacity and 2 GiB guard unchanged.
The numeric report preserves the original failure evidence.

A second attempt then reached the host-memory floor during retention, after
warming 144 CUDA graphs and about 360 MiB of cached grammars. This image keeps
64 graph executables and limits each grammar vocabulary's LRU to 64 MiB.
Evicted graphs/grammars are recreated when needed; active matchers retain their
constraints. These disposable-cache budgets leave more room for requests and
retained snapshots without reducing the shared KV pool. All tests and the
matched stock/Keys throughput campaign below use these smaller cache limits.

The stock → Keys → stock → Keys rehearsal preserved aliases and replayed all
six fixed-seed synthetic prompts identically within each variant. Both ranks
reported the intended 0/78 overlay counts. Stock cache fingerprints stayed
unchanged throughout switching. All 792 generated texts and token counts in
the new stock campaign also matched the retained stock runtime's campaign.
Controller tests cover rejected switches
and automatic previous-variant restoration after a failed start; fault recovery
was not deliberately injected into the live hardware rehearsal.

All 21 Keys finite checks passed: serving/vision/tool-image features, strict
outputs, sampling replay, ordinary/drafted parity through C32, retention,
compaction, request-memory behavior and full-context capacity. Both C32 waves
used 261,120 prompt plus 1,024 reply tokens per stream; all 32 streams decoded
together and replayed identical token sequences. This fixture primes a shared
document while giving active streams independent reservations. The cold
million-token request recovered all three passphrases with 1,048,320 prompt
and 256 reply tokens.

Fresh stock and Keys campaigns each completed 48 waves and 792 requests.
[All stock repetitions](../benchmarks/NATIVE-WORKLOADS-LIBERT-STOCK-20261019.md),
[all Keys repetitions](../benchmarks/NATIVE-WORKLOADS-KEYS-1017-20261019.md) and the
[matched comparison](../benchmarks/KEYS-LIBERT-1017-COMPARISON.md) preserve every
result. Different weight variants can change replies and draft acceptance;
these measurements do not establish model quality or refusal behavior.

The bounded half-hour diagnostic completed 25 mixed
cycles and 2 cold deep requests, totaling 1085 requests.
Both ranks remained healthy with no restart, OOM, poisoned runtime or RoCE
failure. Minimum available memory was 2.86 GiB
on the head and 3.57 GiB on the worker.
Across matched quiet windows, rank anonymous memory plus swap changed by
+2.32 MiB and
+2.20 MiB respectively.
This bounded observation is separate from long-duration endurance qualification.

The LAN installation repeated both hosts' preparation and tensor-byte checks
after the private pair stopped and restoration passed. Twelve fresh synthetic
startup requests passed all context aliases, strict JSON, tools, vision, random
seeds, replay and streaming. Worker-to-head LAN access and the paired monitor
passed on these new rank epochs with zero overlay entries reported on both ranks.
Stock is selected; the prepared Keys option remains available without a model
redownload. The previous stock checkout,
image, assets and current recovery journals remain available for full rollback.

## Original stock 1017 migration

The original stock **DeepSeek-V4.1-Flash-1017** migration used LibertAIDAI's pinned EXL3
2.9 bpw conversion and the matching 1017 Engram and vision inputs. The new
Keys sidecar was reviewed and left off because its K6 replacements differ from
this pack's K5 tensors. [Compatibility, storage and checkpoint rollback](../deployment/CHECKPOINT-1017.md).

Runtime source `e2de6d1b2159a311c65ab8433ef0dc9957f32b6b`, image
`sha256:20c86f35699ad32b245933a455606588834baa9f224b2382b4b3d54c916f0aa2`.
Later documentation and qualification-client commits do not change this image.

The [1017 numeric report](native-checkpoint-1017-20261018.json) records 322 native
build tests, 30 prompt cases against the pinned reference encoder, nine GPU
checks per host and a comparison of every prepared tensor byte against the
intended checkpoint. The FP8 WoA check independently enumerates E4M3 rounding
and checks eager and CUDA-graph results. Both Engram readers agree with buffered
reads on each host.

All 21 finite checks passed: serving features, vision and tool-image ordering,
strict outputs, explicit-seed replay, ordinary/drafted parity through C32,
retention, live reservation compaction, prefill responsiveness, concurrent
long-text memory, full-window C32 and cold million-token retrieval. Both C32
waves reached 32 active decoders with 261,120 prompt and 1,024 reply tokens each;
all 32 sequences matched on replay. This capacity fixture uses a primed shared
document with independent active reservations. The cold million-token request
used 1,048,320 prompt and 256 reply tokens and recovered all three passphrases.

The initial compaction fixture failed to induce the required relocation because
older retained prefixes changed its starting placement. The corrected fixture
first occupies the entire pool with short, non-retainable synthetic requests,
then cancels only those requests. Normal, populated-prefill and active-decode
relocation checks passed on the same ranks and unchanged image, including
independent uncached continuation comparisons. The original failed attempt
remains recorded; it was not evidence of a server corruption fault.

The [fresh workload campaign](../benchmarks/NATIVE-WORKLOADS-STOCK-1017-20261018.md) completed all
48 waves and 792 requests. Three-repetition greedy medians were 93.7/59.3/138.2
tok/s for C1 code/prose/counting and 301.1/252.8/371.0 aggregate tok/s at C32.
Sampled medians were 94.1/56.2/132.4 and 264.2/239.5/362.4 respectively.
Every scored C32 wave reached 32 decoders. Exact request/token counters and
fixed-seed reply hashes matched; every warm-up and scored repetition is retained.

The bounded one-hour diagnostic completed 28 mixed cycles and five cold deep
requests, reaching a million-token window. Its 1,379 requests completed without
rank restart, OOM, poisoned runtime or RoCE failure. All 391 memory observations
per host were complete and clean; minimum available memory was 2.76 GiB on the
head and 3.31 GiB on the worker. Matched quiet windows held the same 64 retained
states, 408 MiB of snapshots and 144 graphs. Rank anonymous memory plus swap
grew by 1.96 MiB and 0.64 MiB respectively. The head's available memory decreased
452.77 MiB as residency and paging changed; its allocated anonymous-plus-swap
footprint remained nearly flat. This bounded observation is separate from the
deferred 24-hour endurance qualification.

After the private pair stopped and host restoration passed, the LAN installation
reused the verified assets and repeated both hosts' prepared-byte and GPU checks.
The new pair passed 12 synthetic startup requests covering all four context aliases,
strict JSON, required tools, red/blue vision, random seeds, returned-seed replay and
streaming parity. Worker-to-head LAN access and the paired monitor passed. These
are new LAN rank epochs, separate from the uninterrupted qualification run.

The prior source, image and head-side assets remain preserved, including a
verified copy of the old worker's prepared cache. Scoped worker reclamation
freed approximately 520 GB after checking both the originals and head backups.
The restore helpers passed synthetic corruption/refusal/retry tests; the full
520 GB restoration has not been rehearsed. See the checkpoint rollback notes.

The following sections preserve the preceding checkpoint's measurements and
runtime identities.

The author requested publication and started the tested native image for
personal LAN use on **2026-10-11**. Finite validation passed; **24-hour endurance
remains deferred**. Personal use does not establish production qualification.

## Previous request-memory correction

Source `0d39dfcfc856756ac889d369f687115c71bdfe2b`, image
`sha256:dbe678e719b1e827535dc2e7cc26aae140c79f673609e7208dbcbca807fe2a6e`.
Later documentation commits do not change this runtime.

The [request-memory investigation](../deployment/REQUEST-MEMORY.md) reproduced
temporary tokenizer/template buffers being retained for the full inference
request. Independent scratch allocation and bounded CPU prompt preparation
reduce the controlled C32/17.6k-text reproduction from 1,153 to 160 MiB peak
RSS. Decode and GPU scheduling do not acquire the preparation lock. Capacity,
features, sampling and the 2 GiB watchdog floor are unchanged.

The [numeric report](native-request-memory-20261012.json) records 318 native
build tests, 84 publication tests, 14 controller tests, seven GPU checks per
host and full prepared-cache byte comparisons. Live checks completed 556
synthetic requests, including features, two long-text C32 waves, two full-262k
C32 waves with matching replay sequences, throughput and LAN access. Minimum
observed available memory was 3.18 GiB on the head and 3.40 GiB on the worker,
with no OOM, poison, RDMA failure, rank restart or watchdog probe error.

All six C32 code/prose/counting rates were within 2.1% of the previous image's
single-run comparison. Greedy C1 code initially measured 93.5 tok/s with six
new graph captures; three follow-up repetitions measured 99.7–100.8 tok/s
with none. The combined four-run median was 99.8 tok/s, within 0.5% of the
headline baseline. All results remain recorded; this regression check does
not replace the three-repetition hero measurements.

The previous source/image is retained on both hosts. This corrected image has
not repeated the twelve-hour observation. The preceding image completed that
observation successfully but later crossed the watchdog floor during concurrent
long text requests; both outcomes are documented in the
[stability report](../deployment/STABILITY.md#twelve-hour-result-and-subsequent-incident).

## Previous allocator correction

Source `84ae3aaa1527515a3cb18236941bf5d4ca565248`, image
`sha256:f6475856dedbc545a09142e6a8cbb9f4d92f29becfbf3fde6f7534ed9065c3a6`.
Later documentation and diagnostic-client commits do not change this runtime.

The [host-memory investigation](../deployment/STABILITY.md) identified freed
glibc arena retention during varying-schema compilation. The profile now sets
`MALLOC_TRIM_THRESHOLD_=131072` inside both containers, and `/health` exposes
optional numeric glibc heap accounting. No host allocator or kernel setting
changes. The KV pool, C32 slots, context ceiling, grammar cache, graph limit and
paired watchdog floor are unchanged.

The rebuilt image passed 316 native tests, 82 publication tests, 14 controller
tests, seven GPU checks per host and full prepared-cache byte comparisons on
both hosts. Fresh serving checks passed text, vision, strict JSON, tool calls,
streaming and drafted/ordinary parity. Both full-window C32 waves reached 32
decoding sessions, and all 32 fixed-seed token sequences matched on replay.
The cold million-token request recovered all three passphrases and reached
1,048,576 total tokens.

The [numeric follow-up](native-host-memory-20261011.json) records the complete
comparison. A warm 128-schema cycle previously grew rank-process anonymous
memory plus swap by 57.2 MiB; two post-change cycles were flat. The matched
quiet-window increase closely tracked live cache warm-up. All 24 code/prose/
counting throughput waves passed, with all 12 C1/C32 rates within 2.7% of the
earlier three-run medians. This was a single-repetition performance regression
check per shape.

The paired monitor recorded no OOM, poison, rank restart or probe error across
260 samples. Minimum available memory was 3.06 GiB on the head and 2.25 GiB on
the worker. LAN serving and the retained previous image were verified after the
checks. The original image's four-hour observation is documented separately;
this finite follow-up did not repeat that run or start a 24-hour test.

## Throughput baseline

Source `6aaec5b3616f4547fabbe2fcc3fb1e779bb75f82`, image
`sha256:baa3fc8d748766476d694da36f3e79ac501f18bed6b9572e36c1c80c4baa7bc7`.
Later documentation commits do not change the measured runtime's identity.

The [throughput evidence](native-throughput-policy-20261010.json) records
315 build tests, seven GPU checks per host, complete prepared-tensor comparisons,
all 11 serving/capacity gates and matched native performance comparisons.
Capacity remains an 8,650,752-token shared pool, 32 slots, a 1,048,576-token
request ceiling and 48 verification rows. Both full-window C32 waves and the
cold million-token/interleaving check passed.

Repeated short C32 drafted throughput improved 4.2%/4.9% end to end and
10.7%/11.4% during eligible steady decode at temperatures 0/1. A later repeat
confirmed the gains. Ordinary decoding still finished those short waves sooner.
Repeated C1 was essentially unchanged; greedy C4 remained 2.4% below its single
earlier baseline. The [report](../benchmarks/NATIVE-DRAFTING.md) retains every
repetition, failed candidates and measurement limits.

The head's minimum available memory was 2.026 GiB, just 26.6 MiB above the
unchanged 2 GiB floor, with paging observed. No sampled floor crossing or OOM
occurred on this image. This narrow margin is not an endurance-stability claim.
The controller's paired health/memory monitor remains enabled.

After the API returned to the authorized LAN endpoint, the
[fresh serving checks](native-serving-check-20261011.json) passed text, vision,
structured output, all four aliases, random seeds and explicit-seed replay.
The worker could reach the API through the head's LAN address. This restart did
not rerun capacity, compaction, recovery or endurance tests.

## Pre-optimization migration evidence

The following results retain runtime `4d48d4ec` and its earlier image identity;
recovery and compaction results are not silently transferred to the throughput
image above.

The corrected image has passed [all 20 functional/capacity clients](native-functional-20261010-r2.json)
at runtime source `4d48d4ec5f3db83a361c2228088d72e27f487d62`. These cover serving
features, ordinary/drafted parity at temperatures 0 and 1 through C32, strict
outputs, retention, both compaction paths, admission and API recovery, full-window
C32, cold million-token retrieval, and an eight-cycle mixed-load soak.
All 32 full-window replay token-ID digests matched. During million-token prefill,
the small arithmetic and JSON requests completed in 0.94 s and 2.36 s.

The previous image failed the 614k deep-context prefill with
`MissingTritonVariant`: an odd indexer block stride misaligned its visibility
view. Both ranks stopped and host restoration passed. The correction preserves
the context and memory budgets. Its [fresh preparation](native-alignment-followup-20261010.json)
passed 293 CPU/server tests, grammar and both hosts' GPU/cache checks. The exact
cold 614k request now completes with all 1,024 output tokens; its output differs
from the Python reference. Three adjacent/odd context checks also passed,
including a 986,895-token cold prompt. The corrected image has completed all
three matched measurement suites. The measured-benefit review accepted faster
deep prefill with the short-workload tradeoffs disclosed in [MIGRATION.md](../MIGRATION.md).
The earlier failed deep suite completed six of ten waves and must not be
presented as a passing comparison.

The earlier [functional evidence snapshot](native-functional-20261010.json)
records the previous-image results at runtime source
`80b399cd023d3a88ad69501c8261143ea622328b` and its exact image.
The corrected image has also passed the [renewed compaction checks](native-compaction-20261010.json):
a populated 262k prefill relocated, and all nine surviving reply prefixes matched
independent zero-cache references. Decoder continuation after relocation passed
as well. Its [paired recovery, controlled reboot and Python rollback rehearsal](native-recovery-20261010.json)
also passed. Its 24-hour run was stopped at the author's request after 526.5
seconds, five mixed cycles and one deep wave; it has not been restarted.
The corrected image's six-minute requested soak
completed 256 requests without eager graph fallbacks; it is not endurance
qualification.

The corrected image's [20-wave primary comparison](native-primary-comparison-20261010-r2.json)
is complete. C1-code end-to-end throughput is 4.9% lower, C16 is 12.4% higher,
and C32 is 9.2% lower than the Python reference. All repetitions are retained;
174 of 178 reported token hashes and full-text digests match. Native C1-code
variability, C4's 10.5% steady-decode regression and C32's drafting costs need
follow-up.

The corrected image's [eight-wave temperature-1 comparison](native-sampled-comparison-20261010-r2.json)
is also complete. C1 is approximately even with Python, while C16 end-to-end
throughput is 15.1% higher. C32 steady decode is 4.1% higher, below the declared
5% benefit threshold; its apparent 11.2% end-to-end gain is affected by a noisy
Python reference. Full-text digests and reported token hashes match for 98 of
100 requests; the two prose replies differ. All repetitions remain included,
including the 12.9% native C1-code end-to-end range. The benefit decision rests
on the separate deep-prefill results rather than this noisy short comparison.

The [longer-reply C4/C32 diagnostic](native-drafting-diagnostic-20261010.json)
completed 16 waves and 288 requests. All 144 ordinary/default reply comparisons
matched in full-text and reported token hashes. Drafting improved C4 steady
decode; at C32 it changed the median by −3.0% at temperature 0 and +0.5% at
temperature 1. Three graph captures in the first drafted C32 wave remain included.
This is an internal native comparison, not a replacement Python benchmark.
Four predeclared additional repetitions of the original C32 temperature-0
workload completed, giving a six-run native end-to-end median of 141.18 tok/s
against the original two-run Python median of 153.22. The original measurements
and policy remain intact; the later native-to-native protocol is separate.

The [complete ten-wave deep-context comparison](native-deep-comparison-20261010.json)
now covers 32k, 128k, 256k, 614k and one million total tokens, with two cold C1-code
runs and 1,024 output tokens at every point. At one million tokens, median
first-token latency falls from 875.16 to 670.41 seconds (23.4% lower), while steady
decode is 89.45 versus 88.84 tok/s. End-to-end output rates improve 13.3–30.1%
from 128k through one million, chiefly through faster prefill. All ten replies
differ between engines, although each engine repeats its own digests. See
[the full interpretation and memory limits](../MIGRATION.md#deep-context-matched-measurements-on-the-corrected-image).
The comparison does not establish a physical-memory saving or production stability.

The earlier image's [primary comparison](native-primary-comparison-20261010.json)
and [temperature-1 comparison](native-sampled-comparison-20261010.json) remain
historical evidence, not qualification of the corrected image. Its earlier
C1-code gain was not reproduced by the corrected image's two primary repetitions.
See the caveats in
[MIGRATION.md](../MIGRATION.md) and the predeclared
[benefit policy](native-benefit-policy-20261010.json). These results do not
establish an overall throughput advantage or production qualification.

The Python reference remains available as the retained, stopped fallback.
Its benchmark and qualification
records are historical; they do not establish native performance or stability.
See [MIGRATION.md](../MIGRATION.md), [native setup](../deployment/README.md)
and [migration rollback](../deployment/MIGRATION-ROLLBACK.md).

The source inventory detects changes to build/engine/controller inputs. It is
not proof of hardware qualification. CI exercises portable and native CPU
contracts, without GPUs or downloaded model weights. No model or proprietary
container layers are included in the repository.
