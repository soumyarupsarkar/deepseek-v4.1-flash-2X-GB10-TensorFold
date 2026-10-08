# Bertholomus v0.5.1 correctness updates

Reviewed the `deepseek-v41-tp2` branch at
[`90b68e063a0b8bba59aaf13340ef16619e751195`](https://github.com/bertholomus/TensorFold/commit/90b68e063a0b8bba59aaf13340ef16619e751195)
on 2026-10-08. Three commits followed the previous selective v0.5 integration:

| Change | Decision |
|---|---|
| [`741a507`](https://github.com/bertholomus/TensorFold/commit/741a507f44e0111367d0e969e5894e0c3129c987): FP32 arithmetic under NVIDIA containers | Included; the recipe also sets the environment before either rank starts |
| [`dfbe519`](https://github.com/bertholomus/TensorFold/commit/dfbe519ff68a0bd7f145e79f8c12b3fa1680c439): opt-in reasoning-loop guard | Included with default off and a local correction for callbacks spanning multiple windows |
| [`90b68e0`](https://github.com/bertholomus/TensorFold/commit/90b68e063a0b8bba59aaf13340ef16619e751195): attribution | Included, crediting Bertholomus's implementation and Capicua25x's novelty signal |

The framework stays on the existing TensorFold 0.6.3 base with selective ports.
Model assets, prepared-weight format, KV capacity, concurrency, draft policy,
prefill chunk size and random-seed selection are unchanged.

## FP32 correctness

The NVIDIA container supplies `TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=1`. Upstream
identified that override as changing FP32 prompt calculations into lower-precision
TF32 calculations and contributing to a reported reasoning loop. This recipe now
sets it to **0** in both rank environments. The family entry point also clears it
for callers outside the recipe and runs upstream's GPU arithmetic probe before
returning a ready engine. A mismatch refuses startup.

The standalone probe reproduced the difference on **both GB10s** using the
preserved container dependencies: override 1 summed to **4096** and was refused;
override 0 summed to the expected **4098** and passed. Both updated ranks select
0 before PyTorch starts. All **225 dependency-inventory lines** match the earlier
image; the three changed engine files were verified inside both running ranks.

This corrects arithmetic; it is not a promise to prevent all reasoning loops.
Replies may differ from the earlier container build, including at the same seed.
Historical output hashes and speeds remain evidence for their original precision
settings; current qualification must be recorded separately.

## Optional reasoning-loop guard

The recipe explicitly selects `TF_LOOP_GUARD=0`. Enable the guard for an
individual thinking request by adding:

```json
{
  "loop_guard": true,
  "chat_template_kwargs": {"enable_thinking": true}
}
```

`TF_LOOP_GUARD=1` makes it the server default; a request's `"loop_guard": false`
overrides that default. A profile change requires a rebuilt, qualified deployment.
The guard is inactive for non-thinking replies, grammar-constrained output and
requests with a positive thinking budget, which keep their existing controls.

The signal checks novelty of token 8-grams in 1,024-token reasoning windows.
Three consecutive windows with less than 2% new 8-grams cause the server to insert
a thinking close and attempt an answer within the remaining output budget.
It does not increase `max_tokens`, guarantee an answer, or evaluate reasoning
quality. Fired requests include `tensorfold.loop_guard: true` in their metadata.

The local adaptation previews every complete window in a callback without
mutating committed history. Upstream's first-boundary-only preview could miss
the close when a callback contained several windows. Small and large callbacks
now close at the same token. A continuation reuses the request's original seed,
including an automatically generated random seed.

## Validation and rollback

Forty-seven publication tests and 222 targeted HTTP tests passed, with one
existing skip. Offline coverage exercises the repeated-token cutoff, natural closure, novel
reasoning, cancellation, output budgets and speculative preview. HTTP tests cover
streamed/non-streamed continuation, explicit and random seeds, per-request
overrides and independent concurrent guards. They use synthetic engine fixtures;
they do not claim that the real model reproduces the reported upstream loop.

The C32 and million-context suites use the selected default, guard off. The
separate guard-on hardware check covers an ordinary code-review prompt, streaming,
four concurrent requests and coexistence with schema/budget controls. It does not
establish guard-on capacity for long reasoning at C32.

The candidate source is `c068898375337c1f2a7bd222e5d1c342b0a83f9c`, built as
image `sha256:928fc8e4416e4494de8e600ef81c3ed60393f3871959d77ae20965bc99d2e8ba`
on both ranks. All nine paired acceptance phases passed in 3,011 seconds:

- Text, red/blue image input, strict JSON/schema/tools and streaming constraints.
- Random unseeded replies, explicit-seed replay and 104 matching default/ordinary
  reply pairs at C16, C24, C32 and a reversed-order C32 repeat.
- Two waves of 32 independent session states, each with 261,120 input and 1,024
  output tokens from an identical primed document. Peak sampled populated history
  was 8,388,192 logical tokens; this is not 32 cold independent document prefills.
- Cold native-million retrieval: 1,048,320 input plus 256 output tokens, all three
  passphrases recovered in 890 seconds. The two smaller concurrent requests
  completed in 0.71 and 1.46 seconds.
- Full-pool admission/release, cancellation, oversized-context rejection and
  nine mixed-load soak cycles.

There were zero CUDA allocation retries or out-of-memory events; all 96 round
graphs remained sealed. Minimum sampled host availability was **2.47 GiB head /
3.17 GiB worker**, against the unchanged 2 GiB watchdog floor. The main watcher
recorded two timeouts in 1,418 health samples; the parity watcher separately
recorded one timeout. These are observation gaps, with all inference checks
completed. Finite qualification does not establish indefinite uptime.

All 132 retained-prefix checks passed in 475 seconds: cold fill, sequential reuse,
extension, repeat parity and least-recently-used eviction. The paired guard
coexistence check also passed: default/off/on replies matched for a non-looping
code-review prompt, including streaming and four concurrent requests; schema,
thinking-budget and non-thinking exclusions stayed effective. Forced looping is
covered by the synthetic engine tests, not claimed as a reproduced model failure.

[Acceptance/retention receipt](../release/upstream-v051-acceptance.json) and
[precision/guard receipt](../release/upstream-v051-correctness.json) retain the
exact scope and hashes of the private source receipts.

## Performance and final serving checks

The complete local suite and unchanged upstream C1/prefill client passed.
The current kit C1 code/prose/counting medians are **94.5 / 59.0 / 137.8 output
tok/s**; cold 32K/128K input divided by first-content latency is **2,000 / 1,837
tok/s**. Local C16/C32 steady medians are **209.9 / 272.2 aggregate output tok/s**;
whole cold-wave medians are **117.2 / 145.5**. [Methods, ranges and previous-build
comparison](../benchmarks/README.md) keep these timing definitions separate.

Of 178 matched local requests, 76 retained the previous TF32 build's token and
text hashes. All 89 repeated fixed-input pairs matched within the updated build.
Every sample remains in the summaries, including one slower local C1 code
repetition. The correction changes arithmetic and can change reply trajectories;
these are measurements of the complete builds, not a quality evaluation.

Normal stop and host restoration passed. The same candidate image was then
restarted and passed text/vision, strict output, random-seeding/replay, worker-to-LAN
access and paired-monitor checks. Both ranks enforce FP32, select the guard off,
and mount the shared assets read-only. The previous image is present on both
nodes. [Current-update lifecycle receipt](../release/upstream-v051-lifecycle.json).
This update did not repeat reboot, worker-loss or previous-image fallback tests;
the earlier [cutover lifecycle evidence](CUTOVER.md) has its own scope.

The previous source/image and private state remain available. Follow the
[update workflow](WORKFLOW.md) and [rollback instructions](ROLLBACK.md); stop and
restore hosts using the active controller before selecting a previous image.

The [source manifest](../release/engine-source.json) fingerprints the current
files and retains the original qualified build as historical provenance.
