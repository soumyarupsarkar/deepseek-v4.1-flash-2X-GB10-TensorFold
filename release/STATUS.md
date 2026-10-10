# Publication and qualification status

The source is published at [soumyarupsarkar/deepseek-v4.1-flash-2X-GB10-TensorFold](https://github.com/soumyarupsarkar/deepseek-v4.1-flash-2X-GB10-TensorFold).
The portable controller has paired hardware evidence for **verified existing-asset
reuse and a fresh image build**. Fresh model acquisition is a separate gate.
There is no release tag associated with this qualification.

## Current October 9 selective update

The selected engine source is `32c4ebea7d0a81808aaa503d88ebe1a84612d0cf`, image
`sha256:973b52dedb5e9e9270fdcaa1840f4ff61076c08fadb3d97c1aea98bef6795834`
on both ranks. It ports Bertholomus's replay-floor correction into the existing
Python engine, adds request-order regressions, and improves watchdog fault
attribution and finite memory qualification. The full native Zig migration is
deferred. C32, the 8,650,752-token shared pool, million-token context, Keys,
vision, strict outputs, random unseeded sampling and the host floor are retained.
The 225-line dependency inventory matches the previous image.

Eighty-four offline tests, 22 CUDA regressions per host and 42 cold request-order
probes passed. All nine acceptance phases passed, including two C32 × 262,144
session waves, cold native-million retrieval, 104 default/ordinary reply pairs
and a six-minute mixed soak. Three matched busy/idle cycles stayed within the
predeclared 256 MiB growth bound: live glibc allocations were essentially flat,
with maximum rank anonymous-plus-swap growth of 18.15 MiB on the head and zero
on the worker. See the [review and results](../deployment/UPSTREAM-V06.md),
[correctness receipt](upstream-v06-correctness.json) and
[acceptance receipt](upstream-v06-acceptance.json).

The five-second acceptance observer had three health timeouts under load.
The separate watchdog recorded no failed samples before the deliberate worker
failure; its minimum observed availability was 2.348 GiB on the head and
3.303 GiB on the worker. Normal stop/restoration, intentional idle worker-loss
cleanup and the selected restart passed, followed by text/vision, LAN, image,
read-only asset and monitor checks. The [lifecycle receipt](upstream-v06-lifecycle.json)
separates the injected fault from natural observations and confirms the prior
image is retained on both nodes. The stopped 24-hour run was not resumed. Original
long-run memory-pressure attribution remains unresolved; no endurance or new
throughput claim follows from these finite passes.

## Historical October 8 FP32 correctness update

The selected engine source is `c068898375337c1f2a7bd222e5d1c342b0a83f9c`, image
`sha256:928fc8e4416e4494de8e600ef81c3ed60393f3871959d77ae20965bc99d2e8ba`
on both ranks. It selectively integrates Bertholomus v0.5.1's FP32 correction and
optional reasoning-loop guard, including a local multi-window callback fix.
The guard stays off by default. Random sampling, assets, capacity and memory
policy are unchanged; the 225-line dependency inventory matches the prior image.

All nine paired acceptance phases and 32-prefix retention passed, including two
C32 × 262,144-token waves, cold native-million retrieval and 104 default/ordinary
reply pairs. The arithmetic difference was reproduced on both GPUs, and the
paired guard coexistence checks passed. Forty-seven publication tests and 222
targeted HTTP tests passed, with one existing skip. See the
[integration report](../deployment/UPSTREAM-V051.md),
[acceptance receipt](upstream-v051-acceptance.json) and
[correctness receipt](upstream-v051-correctness.json).

The complete local suite and unchanged upstream C1/prefill measurements passed.
Normal host restoration and the final restart of the same image passed, including
feature, LAN and monitor checks. [FP32 update lifecycle receipt](upstream-v051-lifecycle.json)
and [measurements](../benchmarks/README.md) record their scope. The previous image
is present on both nodes and installation state is preserved; this update did
not repeat previous-image fallback, worker-loss or reboot tests.

## Historical portable cutover evidence

- Public upstream ancestry retained; private deployment commits, host journals,
  credentials and raw operational logs omitted.
- The cutover verified 476 engine/client files against its then-selected
  snapshot. [engine-source.json](engine-source.json) now records current
  fingerprints and the historical baseline provenance. The original private
  engine/image identifiers are not publicly fetchable artifacts.
- Source `2f65892284376d6a59eda1270e3a9ab59f79897b` built and transferred as the
  identical image on both GB10s. All 225 dependency-inventory lines match the
  previous image; installed runtime source identity was checked.
- Existing pinned model/Keys/Engram/vision files and completed prepared caches
  were verified, reused under new ownership, and served through read-only
  shared-asset mounts. Mutable kernel caches were compiled separately.
- Text, vision, strict JSON/schema/tools, sampling, C16/C24/C32 parity, two full
  C32 session waves, native-million retrieval, admission/cancellation, mixed
  soak and 32-prefix retention passed. [Acceptance receipt](cutover-acceptance.json).
- The complete local headline suite and unchanged upstream C1/cold-prefill
  methods were repeated. All 178 matched local replies retained the original
  token and text hashes. [Measurements](../benchmarks/README.md).
- Interrupted-controller cleanup and idle worker-loss cleanup restored both
  hosts. The preserved old server also passed its fallback checks and was stopped
  before the selected new restart. The [lifecycle receipt](cutover-lifecycle.json)
  and [cutover report](../deployment/CUTOVER.md) record scope, host checks and limits.
- Thirty-nine offline contract tests and source/publication checks passed.
  [Hosted CI for the deployed source](https://github.com/soumyarupsarkar/deepseek-v4.1-flash-2X-GB10-TensorFold/actions/runs/37735776995)
  also passed. Git identity is configured locally; global Git configuration is
  unchanged.

The [original preparation receipt](preparation-checks.json) is a historical
snapshot from before publication and hardware cutover. Its then-pending gates
and publication flags do not describe the current state. Later documentation
and evidence commits do not change the pinned serving source/image; see the
[development/deployment workflow](../deployment/WORKFLOW.md).

## Remaining before a release tag or stronger claims

1. Exercise fresh Hugging Face download/extraction, replication and the complete
   lifecycle on an idle pair. The reuse migration did not download or regenerate
   the existing model assets. The Docker dependency inventory is not a hermetic
   package lock.
2. Exercise actual reboot recovery. Reboot-aware decisions have offline coverage;
   this cutover tested interrupted-controller and worker-process failure without
   rebooting either host.
3. Finish code/model/container licensing and modified-file notice review, retain
   Apache/MIT notices, verify the exact pinned asset terms, and confirm inherited
   history is suitable for the intended public fork.
4. Add broader long-context and overlay-quality evaluations before making stronger
   quality or comparative performance claims. A finite capacity/soak run and one
   three-needle retrieval test do not establish indefinite uptime or general
   million-context quality. The measured head RAM margin is limited.
5. Re-scan every publication ref and inspect the final diff for each release;
   configure a reporting contact and confirm CI for the exact release commit.

No raw host inventory, private recovery journal, credential or ordinary inference
traffic is needed in the public evidence bundle. Keep those records with the
installation so it can be stopped and restored with its own controller.
