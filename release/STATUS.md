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
including a 986,895-token cold prompt. Renewed matched performance qualification
is running. The failed deep suite completed six of ten waves and must not be
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

The earlier image's [20-wave primary comparison](native-primary-comparison-20261010.json)
is complete. Its observed end-to-end medians include a 6.2% C1-code gain and a 7.7%
C32 regression. The [eight-wave temperature-1 comparison](native-sampled-comparison-20261010.json)
is also complete: C1 code is roughly even, C16 is faster, and C32's apparent
end-to-end gain is affected by a noisy Python reference. C4's steady-decode
regression and native C1 variability need follow-up; deeper-context measurements
remain pending. See the caveats in
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
