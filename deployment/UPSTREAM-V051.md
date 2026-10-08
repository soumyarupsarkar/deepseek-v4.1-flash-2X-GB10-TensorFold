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

Offline coverage exercises the repeated-token cutoff, natural closure, novel
reasoning, cancellation, output budgets and speculative preview. HTTP tests cover
streamed/non-streamed continuation, explicit and random seeds, per-request
overrides and independent concurrent guards. They use synthetic engine fixtures;
they do not claim that the real model reproduces the reported upstream loop.

Paired hardware qualification and current performance results will be recorded
after the selected image is built. The previous source/image and private state
must remain available until those checks pass. Follow the
[update workflow](WORKFLOW.md) and [rollback instructions](ROLLBACK.md); stop and
restore hosts using the active controller before selecting a previous image.

The [source manifest](../release/engine-source.json) fingerprints the current
files and retains the original qualified build as historical provenance.
