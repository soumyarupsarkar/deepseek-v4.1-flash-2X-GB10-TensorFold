# Native engine migration (qualification in progress)

The native candidate is **not qualified for production**. The image that passed
the feature and capacity checks below later failed the 614k deep-context test.
Both ranks stopped and both hosts passed restoration checks. The corrected
image has passed preparation, the exact cold 614k regression request and three
adjacent/odd context checks, and is repeating the rest of live qualification.
Matched performance, an independent cold compaction reference, recovery and a
new 24-hour endurance run remain open. The published Python
deployment remains the qualified fallback and is stopped during this work.

## Exact inputs and evidence

The native engine starts at Bertholomus's
[`4e80f05`](https://github.com/bertholomus/TensorFold/commit/4e80f05ecba89a4e90d16375ade2eddbdc0a10c4),
with the v0.6.1 recipe and kernel builders at
[`5e90ec9`](https://github.com/bertholomus/deepseek-v4.1-tensorfold-tp2-2xgb10/tree/5e90ec9302149049e8f019ea035827cb24c206f8).
The hardware results below belong to the failed candidate's runtime source
`80b399cd023d3a88ad69501c8261143ea622328b` and image
`sha256:5835a26f281d1dd2ddd868648a5ac6048d6924e02ca0d1a5a1cd1324949cbb6d`.
Later documentation and qualification-client commits do not change which
runtime produced those results.

The rollback source is this fork's `32c4ebea7d0a81808aaa503d88ebe1a84612d0cf`,
documented and published in `29c1a04ecd75ea56ba85502279aa39b0bf6705f8`.
Its [20-case Python baseline](deployment/release/native-python-baseline-20261010.json)
is separate from native measurements. Historical Python results do not qualify
the native implementation.

The [October 10 functional evidence](release/native-functional-20261010.json)
records 20 completed synthetic client runs, their source and receipt hashes,
selected counters, and the remaining acceptance gates. Raw installation records
remain private. The export does not include real inference traffic or establish
a throughput advantage.

## Completed checks on the previous candidate image

| Area | Observed result | Scope |
| --- | --- | --- |
| Build and preparation | 90 build steps and 291 CPU/server tests passed; native grammar and GPU primitive checks passed on both ranks | Full native cache comparison checked 143,770 entries and 106,107,109,192 bytes per rank against the intended Keys checkpoint |
| Serving features | Text, vision, JSON object/schema, required tools, thinking budgets, seeds, aliases, Chat, Responses and Messages passed | Includes JPEG/WebP through all three APIs; synthetic fixtures |
| Drafting parity | Ordinary/drafted token hashes matched at C4/8/16/24/32, at temperatures 0 and 1 | Zero cached tokens, observed requested concurrency, drafts for every request; these fixtures compare the reported 12-hex token hashes |
| Constrained C32 | 32 schemas and 32 required tool calls passed at each temperature | All validators passed and all four waves observed C32 decoding |
| Retention | 32 distinct 16k histories passed cold admission, replay, extension and extended replay | 64 retained states; 408 MiB snapshot storage |
| Decoder compaction | Eight live survivors relocated; a selected survivor's continued output matched fresh solo execution | The witness includes at least 64 tokens generated after the relocation checkpoint |
| Full-window C32 | Two waves of 32 sessions each completed 261,120 prompt tokens plus 1,024 reply tokens | Exact returned token IDs matched across waves; one identical primed document with independent active session extents |
| Million-token request | A cold 1,048,320-token prompt plus 256-token reply completed and retrieved all three synthetic passphrases | Small arithmetic and JSON requests finished during prefill in 0.96 s and 2.53 s, within the declared 30 s limit |
| Incremental prefill | Five small requests completed in 8.18 s during a separate 262k prefill | Short/image output parity and cancellation checks passed; the long-text solo comparison used a retained prefix |
| Admission and API recovery | Full-pool queuing, release, cancellation, malformed requests and return to idle passed | This does not replace paired-process or reboot recovery |
| Short soak | Eight C32 cycles completed 256 text/schema/vision requests over a six-minute requested run | No eager graph fallbacks; this does not replace 24-hour endurance |

The profile independently sets an **8,650,752-token shared KV pool**, a
**1,048,576-token request limit**, **32 stream slots**, and a **48-row draft
round budget**. C32 capacity uses retained copies of the same synthetic document;
it does not measure simultaneous cold prefill of 32 different long documents.
Correctness-test wall times are not matched performance results.

Partial-prefill compaction remains provisional. A populated partial prefill
was observed relocating and its continued reply matched the client's solo
comparison, but that comparison did not require zero cached tokens. Acceptance
requires reproducing the saved post-relocation reply prefix from an independent
cold request. The failed launch has ended, so the new image must repeat the
relocation and independent cold comparison together. The public client now
evicts retained checkpoints and requires zero cached tokens for that comparison.

## 614k failure and correction

The deep-context suite completed both 32k, 128k and 256k repetitions, then failed
while prefilling 613,376 tokens for a 1,024-token reply. Both ranks reported
`MissingTritonVariant` for the FP32 index-score kernel. Its captured variants
require a 16-byte-aligned visibility pointer. The scratch-budget calculation
selected 27-row blocks; each visibility entry is eight bytes, so the second
block violated that alignment. The later peer-disconnect messages followed
paired shutdown and were not the initial failure.

Multi-block strides now round down to an even number of rows (26 in this case).
Single odd blocks remain unchanged. Two CPU regressions fail with the original
calculation and pass with the correction, including adjacent and odd context
sizes. This preserves the configured request limit, shared KV pool and scratch
budget. The actual failing GPU request now passes on the corrected image with
613,376 uncached prompt tokens and all 1,024 output tokens. Its generated output
differs from the Python reference; this is a successful crash regression, not an
output-parity claim. Three additional cold prompts of 613,375, 613,377 and
986,895 tokens each completed their 64-token replies, with zero cached tokens
and no reported probe or rank errors. Full qualification remains in progress.
Six completed waves out of ten on the earlier image do not constitute a passing
deep-context suite or a complete comparison graph.

The [alignment follow-up evidence](release/native-alignment-followup-20261010.json)
binds the new preparation to source
`4d48d4ec5f3db83a361c2228088d72e27f487d62` and image
`sha256:83752d9d3bc7da632fd195332963501e9ca5208a8e2fcf409e781e985049aafd`.
Its fresh build passed 293 CPU/server tests and the native grammar test. Both
hosts passed seven GPU checks and full comparison of 143,770 cache entries
(106,107,109,192 bytes per rank), with zero mismatches. The renewed live suite
has completed the exact 614k failure case and the adjacent/odd context checks.
It is repeating feature, capacity, cold compaction and matched performance checks.
Preparation is not serving or production qualification.

## Primary matched measurements (partial qualification)

The [complete primary comparison](release/native-primary-comparison-20261010.json)
contains 20 scored waves and 178 requests, with two repetitions per workload.
Actual prompt hashes, output budgets and zero cached tokens match. These are
observed test medians on the pinned images, not a completed benefit decision:

| Workload, temperature 0 | Prompt / reply tokens per request | Python end-to-end tok/s | Native end-to-end tok/s | Change |
| --- | --- | ---: | ---: | ---: |
| C1 code | 43 / 384 | 89.88 | 95.41 | +6.2% |
| C4 mixed | 1,024 / 256 | 95.58 | 90.98 | −4.8% |
| C16 mixed | 1,024 / 256 | 117.37 | 132.10 | +12.6% |
| C32 mixed | 1,024 / 256 | 153.22 | 141.38 | −7.7% |

The full comparison retains every workload and repetition. Reported token
hashes matched for 174 of 178 requests. The four differences are the two C1
prose replies and the two 128k replies; their rate differences do not isolate
runtime speed on identical generated output. C1 code, C4 and C32 also matched
full text digests. C16's Python end-to-end repetitions differed by 16.4%, so its
median needs that variability context.

C4's eligible steady-decode median fell 11.1%, with only about three seconds
of eligible interval per repetition and no native graph captures in either
wave. A longer-reply ordinary/default diagnostic is prepared to investigate it;
it has not run. A missing native steady interval at 32k stays null. The separate
deep-context suite uses longer replies to make those measurements more useful.

The [benefit policy](release/native-benefit-policy-20261010.json) was declared
before native matched measurements. Deeper-context results,
memory interpretation, and the remaining functional/recovery/endurance gates
are still required. Engine-specific cache eviction occurs outside scored timing:
the Python client inserted 32 prefixes, and the native client inserted 64
fixtures to displace its retained states. Every scored request reports zero
cached tokens. Client changes adapt native counters and record post-response
drain outside stream timings; native graph-capture cost remains included.

## Temperature-1 matched measurements

The [sampled comparison](release/native-sampled-comparison-20261010.json)
contains eight scored waves and 100 requests, with two repetitions per workload
at temperature 1 and the same explicit seed. Every request was cold. These are
end-to-end rates, including prefill and admission:

| Workload | Prompt / reply tokens per request | Python tok/s | Native tok/s | Change |
| --- | --- | ---: | ---: | ---: |
| C1 code | 43 / 384 | 88.86 | 89.42 | +0.6% |
| C1 prose | 23 / 384 | 56.62 | 60.74 | +7.3% |
| C16 mixed | 1,024 / 256 | 105.72 | 125.48 | +18.7% |
| C32 mixed | 1,024 / 256 | 118.87 | 132.60 | +11.6% |

Full text digests and reported token hashes matched for 98 of 100 requests.
Both prose replies differed, so their rate change does not isolate runtime
speed on identical output. Native C1-code repetitions ranged from 81.94 to
96.91 tok/s; the 0.6% median difference does not establish a sampled C1 gain.
There were no native graph captures in these eight waves.

Python C32 repetitions were 134.04 and 103.69 tok/s. The slower run had an early
admission stall associated with system paging. Native repetitions were 132.66
and 132.53 tok/s. The noisy Python median makes the apparent 11.6% end-to-end
gain unsuitable as sole benefit evidence. Eligible steady-decode medians were
219.86 and 233.45 tok/s (+6.2% native), whereas temperature-0 C32 steady decode
was 6.5% slower. The result depends on workload and sampling configuration.

The memory observations include different resident and swapped states. They
do not establish a reduction in physical memory requirements. The deep-context
comparison and investigation of the short C4 and C1 measurements remain open.

## Native integration changes

The integration separates shared-pool capacity from each request's context
limit, expands bounded stream/verifier/drafter/MoE/graph storage for C32, adds
DRM-backed compressed KV allocation, and preserves the reversible deployment
controller's host journals. It implements constrained decoding, required tools,
bounded retained state, live extent compaction and incremental prefill.

Hardware qualification exposed two implementation defects that were corrected
before the current image: wide router rounds requested kernel variants absent
from the pinned kit, and forced reasoning closure could introduce whitespace
rejected by a root schema. Router rounds now use supported slices; an independent
GPU check compares widths 1–48 against one-row launches. Constrained reasoning
closure leaves the first answer token to the grammar mask.

The earlier native prefill path blocked other requests for the whole prompt.
The current implementation returns between 2,048-token chunks, preserves each
prompt's slot, restore position and image embeddings, and interleaves decoding
with prefill. It follows the Python dual-GB10 engine's 50% decode-share approach.
An adapter-level regression also checks that the CUDA context-binding adapter
forwards both incremental callbacks and cancellation. Earlier images' passes
and failures remain separate from this image's evidence.

The serving engine, scheduler and sampler are native. The xgrammar compiler is
a pinned C++ library. Offline compressed-token-map preparation uses the pinned
`tokenizers` package; upstream's bounded Pillow helper handles image codecs
other than the native PNG path. Native inference does not use a Python model
engine or PyTorch tensor loop. Fresh rank-cache preparation has a CPU-only native
command. Imported caches remain read-only and require complete comparison with
the intended checkpoint: a legacy `prepared_cache_producer` field identifies
a known format/loader revision, not proof of which commit wrote an imported file.

## Remaining cutover gates

1. Complete renewed selected-image feature/capacity checks, including
   the independent cold partial-prefill compaction comparison.
2. Finish matched synthetic throughput, latency and memory comparisons against
   the Python reference, including temperature-1 sampling and deep context.
   Require a measured benefit without unexplained material regressions; investigate
   noisy or marginal results before selecting a production profile.
3. Recheck paired failure, interrupted startup, host restoration and controlled
   reboot recovery on the selected runtime/image. Earlier-image lifecycle checks
   are insufficient.
4. Complete a **new bounded 24-hour** synthetic qualification with quiet memory
   windows, mixed serving and deep-context checks. Preserve failed or interrupted
   receipts. The previously user-stopped endurance process stays stopped.
5. Finish source, attribution, setup/rollback and sanitized-evidence review, then
   cut over only if every gate passes. Otherwise restore the qualified Python
   deployment and document the concrete blockers.

## Rollback contract

Preserve the qualified checkout, images on both hosts, verified model assets,
installation ownership and host journals. Original checkpoints and imported
rank caches are immutable inputs; generated native kernels and mutable caches
use separate directories. Stop the candidate through its own controller and
verify host restoration before starting the qualified checkout with its matching
image. Never replace current ownership journals with old copies.

Candidate builds, tests and publication edits do not change the serving selector.
Keep private host configuration, operational logs, credentials and raw receipts
outside Git. See [migration rollback](deployment/MIGRATION-ROLLBACK.md) and the
[host recovery procedure](deployment/ROLLBACK.md).
