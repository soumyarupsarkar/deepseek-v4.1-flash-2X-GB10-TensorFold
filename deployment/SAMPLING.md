# Sampling and replay

The native engine supports `TENSORFOLD_SEED_MODE=prompt` and `random`. Its code default is prompt-derived; this deployment explicitly selects **random**. The API defaults are temperature 1, top-p 0.95 and top-k 20. Benchmarks specify their sampling settings separately.

In random mode, an absent or null request seed selects fresh 64-bit entropy. `tensorfold.sampling_seed` returns the effective seed as a decimal string, which may exceed JavaScript's exact integer range. Send that string back as `seed` for replay. Explicit zero is a real seed and overrides either mode. Greedy requests (`temperature=0`) return a null sampling seed and can produce identical replies regardless of seed mode.

Prompt mode uses the native engine's prompt-derived keyed seed rule. Repeated identical prompts can therefore produce identical sampled answers. Changing seed mode does not resize the KV pool or disable draft verification.

Random mode provides the familiar client behavior of varying unseeded sampled requests. It does not promise vLLM token parity. Replay comparisons must fix the checkpoint/overlay, image, backend, numerical settings, sampling parameters and input. Cross-version Python/native replay is a separate correctness observation, not a seed-mode guarantee.

Strict JSON/schema and tool-constrained requests use ordinary decoding by default. OpenAI Chat, Completions and Responses callers can opt into native speculative decoding with `"draft": true`; `"draft": false` explicitly selects ordinary decoding. Both modes enforce the same xgrammar constraints. The measured C1 benefit and C32 cost are documented in [parity and throughput evidence](UPSTREAM-20261030.md).

The Anthropic adapter does not forward this extension and keeps ordinary constrained decoding. Health reports support in `structured_drafts` and the default in `structured_drafts_default`. `ignore_eos: true` with a grammar or tool constraint returns HTTP 400 before generation.

The `TF_DSV41_TOOL_GRAMMAR=required` deployment setting constrains required/named calls and explicit strict tools; optional non-strict automatic tool selection remains unconstrained. `all` and `off` are alternative build/profile choices that need their own qualification.

The reasoning-loop guard is off by default. A boolean request `loop_guard` can opt in or out; null inherits the server default. Non-thinking requests, structured output and an explicit positive thinking budget exclude the guard. This is the native engine's repetition detector; the previous Python novelty-based guard is documented in the historical [v0.5.1 report](UPSTREAM-V051.md). Enabling either guard can change output when it fires.

Change profile settings through a reviewed, rebuilt deployment. Do not edit an initialized installation's ownership records to bypass configuration checks. Live qualification receipts establish which replay, streaming and concurrent cases have actually passed on a particular image.
