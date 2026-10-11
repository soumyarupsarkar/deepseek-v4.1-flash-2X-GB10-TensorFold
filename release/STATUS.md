# Native release status

This branch is a migration candidate, not a qualified production release.

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
three matched measurement suites; performance acceptance remains pending.
The earlier failed deep suite completed six of ten waves and must not be
presented as a passing comparison.

The earlier [functional evidence snapshot](native-functional-20261010.json)
records the previous-image results at runtime source
`80b399cd023d3a88ad69501c8261143ea622328b` and its exact image.
The corrected image has also passed the [renewed compaction checks](native-compaction-20261010.json):
a populated 262k prefill relocated, and all nine surviving reply prefixes matched
independent zero-cache references. Decoder continuation after relocation passed
as well. Matched performance and memory acceptance, recovery (including a
controlled reboot and Python rollback rehearsal), and a new bounded 24-hour
endurance run remain pending. The corrected image's six-minute requested soak
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
including the 12.9% native C1-code end-to-end range. No measured-benefit gate has
been accepted.

The [longer-reply C4/C32 diagnostic](native-drafting-diagnostic-20261010.json)
completed 16 waves and 288 requests. All 144 ordinary/default reply comparisons
matched in full-text and reported token hashes. Drafting improved C4 steady
decode; at C32 it changed the median by −3.0% at temperature 0 and +0.5% at
temperature 1. Three graph captures in the first drafted C32 wave remain included.
This is an internal native comparison, not a replacement Python benchmark.
Four predeclared additional repetitions of the original C32 temperature-0
workload are running to investigate its near-threshold regression. The original
measurements and policy remain intact.

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

The Python reference remains the qualified fallback and is stopped during the
loopback candidate's hardware qualification. Its benchmark and qualification
records are historical; they do not establish native performance or stability.
See [MIGRATION.md](../MIGRATION.md), [native setup](../deployment/README.md)
and [migration rollback](../deployment/MIGRATION-ROLLBACK.md).

The source inventory detects changes to build/engine/controller inputs. It is
not proof of hardware qualification. CI exercises portable and native CPU
contracts, without GPUs or downloaded model weights. No model or proprietary
container layers are included in the repository.
