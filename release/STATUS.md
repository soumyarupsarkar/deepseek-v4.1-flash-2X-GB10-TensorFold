# Native release status

The author requested publication and started the tested native image for
personal LAN use on **2026-10-11**. Finite validation passed; **24-hour endurance
remains deferred**. Personal use does not establish production qualification.

## Current runtime

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
